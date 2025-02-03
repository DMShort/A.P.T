import os
from dotenv import load_dotenv
import discord
import matplotlib.pyplot as plt
import requests
import aiohttp
from discord.ext import commands, tasks
import asyncio
import sqlite3
import datetime
import io
from io import BytesIO
import traceback
import pandas as pd
from discord import Option
import aiosqlite


load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
API_URL_COMMODITIES = "https://api.uexcorp.space/2.0/commodities"
API_URL_PRICES = "https://api.uexcorp.space/2.0/commodities_prices?id_commodity={}"

# Function to fetch commodity names from the database
async def fetch_commodity_names():
    conn = sqlite3.connect('organizations.db')
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT commodity_name FROM commodity_prices")
    commodities = [row[0] for row in cursor.fetchall()]
    conn.close()
    return commodities

# Universal Autocomplete Function
async def commodity_autocomplete(ctx: discord.AutocompleteContext):
    commodities = await fetch_commodity_names()
    return [c for c in commodities if ctx.value.lower() in c.lower()]
    
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
# Database setup
def setup_db():
    conn = sqlite3.connect('organizations.db')
    cursor = conn.cursor()

    # Create tables for organizations, members, and ranks
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS organizations (
        org_id INTEGER PRIMARY KEY AUTOINCREMENT,
        org_name TEXT,
        description TEXT,
        leader_id INTEGER
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS members (
        user_id INTEGER,
        org_name TEXT,
        role TEXT,
        points INTEGER,
        PRIMARY KEY (user_id, org_name),
        FOREIGN KEY (org_name) REFERENCES organizations(org_name)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ranks (
        rank_name TEXT,
        org_name TEXT,
        PRIMARY KEY (rank_name, org_name),
        FOREIGN KEY (org_name) REFERENCES organizations(org_name)
    )
    ''')

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS roles (
        org_name TEXT,
        role_name TEXT,
        income_share REAL DEFAULT 0,
        PRIMARY KEY (org_name, role_name)
    )
""")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS commodity_prices (
        id INTEGER PRIMARY KEY,
        commodity_name TEXT NOT NULL,
        price_buy REAL,
        price_sell REAL,
        weight_scu INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('''\
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER,
        channel_id INTEGER
        )
    ''')

    conn.commit()
    conn.close()

#Database End

bot = commands.Bot(command_prefix="/", intents=intents)

#define alert channel
ALERT_CHANNEL_ID = 1334357654906212364

#define previous Data
previous_prices = {}
ALERT_THRESHOLD = 0.05

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}, V1")
    setup_db()
    # Run the initial fetch on startup
    # await fetch_initial_commodity_data()

    if not check_commodity_prices.is_running():
        check_commodity_prices.start()

    if not fetch_commodity_prices.is_running():
        fetch_commodity_prices.start()
    
    # Create an embed for the message
    embed = discord.Embed(
        title="🤖 A.P.T - Automated Personal Trader", 
        description="I am ready to assist with your trading needs!", 
        color=discord.Color.blue()
    )
    embed.add_field(name="🔄 Initializing Systems...", value="Please wait while I prepare...", inline=False)
    embed.add_field(name="📊 Building Databases...", value="Fetching the latest market data...", inline=False)
    embed.add_field(name="✅ Ready to assist!", value="You can now use my trading commands.", inline=False)
    # Check if the bot has an avatar before setting the footer
    if bot.user.avatar:
        embed.set_footer(text="Powered by A.P.T", icon_url=bot.user.avatar.url)
    else:
        embed.set_footer(text="Powered by A.P.T")

    for guild in bot.guilds:
        # Get the first text channel available
        for channel in guild.text_channels:
            # Send the startup message
            await channel.send(embed=embed)
            break  # Stop after sending the message to the first text channel

#Database Functions
# Function to create an organization
def create_organization(org_name, description, leader_id):
    conn = sqlite3.connect('organizations.db')
    cursor = conn.cursor()

    # Insert the organization into the database
    cursor.execute('''
    INSERT INTO organizations (org_name, description, leader_id) VALUES (?, ?, ?)
    ''', (org_name, description, leader_id))

    # Create default ranks for the organization (Leader, Officer, Member)
    cursor.execute('''
    INSERT INTO ranks (rank_name, org_name) VALUES
    ('Leader', ?),
    ('Officer', ?),
    ('Member', ?)
    ''', (org_name, org_name, org_name))

# Insert the creator as a member with the 'Leader' rank
    cursor.execute('''
    INSERT INTO members (user_id, org_name, role, points) VALUES (?, ?, ?, ?)
    ''', (leader_id, org_name, 'Leader', 0))  # Assuming points start at 0

    conn.commit()
    conn.close()

# Function to join an organization
def join_organization(user_id, org_name):
    conn = sqlite3.connect('organizations.db')
    cursor = conn.cursor()

    # Check if the organization exists
    cursor.execute('SELECT * FROM organizations WHERE org_name = ?', (org_name,))
    if cursor.fetchone() is None:
        conn.close()
        return f"❌ The organization `{org_name}` does not exist."

    # Check if the user is already a member
    cursor.execute('SELECT * FROM members WHERE user_id = ? AND org_name = ?', (user_id, org_name))
    if cursor.fetchone() is not None:
        conn.close()
        return f"❌ You are already a member of `{org_name}`."

    # Add the user as a member with the default role "Member"
    cursor.execute('''
    INSERT INTO members (user_id, org_name, role, points) VALUES (?, ?, ?, ?)
    ''', (user_id, org_name, "Member", 0))

    conn.commit()
    conn.close()
    return f"✅ You have joined the organization `{org_name}` as a Member!"

# Function to award points to a member
def award_points(user_id, member_id, org_name, points):
    conn = sqlite3.connect('organizations.db')
    cursor = conn.cursor()

    # Check if the organization exists
    cursor.execute('SELECT * FROM organizations WHERE org_name = ?', (org_name,))
    if cursor.fetchone() is None:
        conn.close()
        return f"❌ The organization `{org_name}` does not exist."

    # Check if both the user and member are in the organization
    cursor.execute('SELECT * FROM members WHERE user_id = ? AND org_name = ?', (user_id, org_name))
    if cursor.fetchone() is None:
        conn.close()
        return f"❌ You are not a member of `{org_name}`."

    cursor.execute('SELECT * FROM members WHERE user_id = ? AND org_name = ?', (member_id, org_name))
    if cursor.fetchone() is None:
        conn.close()
        return f"❌ The member is not a member of `{org_name}`."

    # Award points
    cursor.execute('''
    UPDATE members SET points = points + ? WHERE user_id = ? AND org_name = ?
    ''', (points, member_id, org_name))

    conn.commit()
    conn.close()
    return f"✅ {points} points awarded to the member in `{org_name}`."
    # Function to leave an organization
def leave_organization(user_id, org_name):
    conn = sqlite3.connect('organizations.db')
    cursor = conn.cursor()

    # Check if the user is in the organization
    cursor.execute('SELECT * FROM members WHERE user_id = ? AND org_name = ?', (user_id, org_name))
    if cursor.fetchone() is None:
        conn.close()
        return f"❌ You are not a member of `{org_name}`."

    # Remove the user from the organization
    cursor.execute('DELETE FROM members WHERE user_id = ? AND org_name = ?', (user_id, org_name))

    # Check if the organization has any remaining members
    cursor.execute('SELECT COUNT(*) FROM members WHERE org_name = ?', (org_name,))
    remaining_members = cursor.fetchone()[0]

    # If no members remain, delete the organization
    if remaining_members == 0:
        cursor.execute('DELETE FROM organizations WHERE org_name = ?', (org_name,))
        cursor.execute('DELETE FROM ranks WHERE org_name = ?', (org_name,))
        conn.commit()
        conn.close()
        return f"⚠️ You were the last member. Organization `{org_name}` has been deleted."

    conn.commit()
    conn.close()
    return f"✅ You have successfully left `{org_name}`."
# Database Function End

#task to check commodity prices periodically
@tasks.loop(minutes=10)
async def check_commodity_prices():
    try:
        response = requests.get(API_URL_COMMODITIES)
        data = response.json()
        print("✅Getting Commodity Prices.")

        if data["status"] != "ok" or not data["data"]:
            print("❌ Error: Unable to fetch commodity data.")
            return

        commodities = data["data"]
        alerts = []

        for commodity in commodities:
            name = commodity["name"]
            current_price = commodity["price_sell"]

            # Check if current price is valid
            if current_price is None or current_price <= 0:
                continue  # Skip invalid price

            # Compare the current price with the previous price
            if name in previous_prices:
                previous_price = previous_prices[name]
                price_change = (current_price - previous_price) / previous_price

                if abs(price_change) >= ALERT_THRESHOLD:
                    alerts.append((name, previous_price, current_price, price_change))

            # Update the previous price for next comparison
            previous_prices[name] = current_price

        if alerts:
            alert_message = "**Commodity Price Alerts:**\n"
            for alert in alerts:
                name, old_price, new_price, change = alert
                direction = "increased" if change > 0 else "decreased"
                percentage_change = abs(change) * 100
                alert_message += (f"**{name}** has {direction} by {percentage_change:.2f}%!\n"
                                  f"Previous Price: {old_price} UEC\n"
                                  f"New Price: {new_price} UEC\n\n")

            alert_channel = bot.get_channel(ALERT_CHANNEL_ID)
            if alert_channel:
                await alert_channel.send(alert_message)

    except Exception as e:
        print(f"❌ Error: {str(e)}")

#Task Loop Commodity Prices
@tasks.loop(minutes=5)
async def fetch_commodity_prices():
    print("✅ fetch_commodity_prices() function is running...")  # Debug log
    conn = sqlite3.connect('organizations.db')
    cursor = conn.cursor()

    # Fetch commodity data from API
    async with aiohttp.ClientSession() as session:
        url = "https://api.uexcorp.space/2.0/commodities"
        async with session.get(url) as response:
            if response.status == 200:
                response_data = await response.json()

                if response_data.get("status") == "ok":
                    commodities = response_data.get("data", [])
                    print(f"✅ Fetched {len(commodities)} commodities.")  # Debug log

                    # Insert data into the database
                    for commodity in commodities:
                        commodity_name = commodity.get("name")
                        price_buy = commodity.get("price_buy")
                        price_sell = commodity.get("price_sell")
                        weight_scu = commodity.get("weight_scu")

                        if commodity_name and price_buy and price_sell:
                            cursor.execute(
                                "INSERT INTO commodity_prices (commodity_name, price_buy, price_sell, weight_scu, timestamp) VALUES (?, ?, ?, ?, datetime('now'))",
                                (commodity_name, price_buy, price_sell, weight_scu)
                            )

                    # Commit the changes
                    conn.commit()

                    print(f"✅ Inserted {len(commodities)} commodity prices into the database.")  # Debug log
                else:
                    print("❌ Failed to fetch valid data. API response status not 'ok'.")

    # Remove data older than 7 days
    cursor.execute("DELETE FROM commodity_prices WHERE timestamp < datetime('now', '-7 days')")

    conn.commit()
    conn.close()
    print("✅ Old commodity data older than 7 days removed.")  # Debug log

# Run the task once when the bot starts up
#async def fetch_initial_commodity_data():
   # print("✅ Initial fetch of commodity prices on startup.")
   # await fetch_commodity_prices()

#Commodity Check
@bot.slash_command(name="commodity", description="Enter Commodity Name")
async def commodity(
    ctx, 
    name: Option(str, "Choose a commodity", autocomplete=commodity_autocomplete)
):
    """Fetches commodity details from SQLite database asynchronously"""
    try:
        # ✅ Acknowledge the command before querying the database
        await ctx.defer()

        async with aiosqlite.connect('organizations.db') as conn:
            cursor = await conn.execute('''
                SELECT price_buy, price_sell, COALESCE(weight_scu, 0), timestamp 
                FROM commodity_prices 
                WHERE commodity_name = ? 
                ORDER BY timestamp DESC 
                LIMIT 1
            ''', (name,))
            result = await cursor.fetchone()

        if not result:
            await ctx.respond(f"❌ No data found for commodity: {name}")
            return

        # ✅ Unpack the result
        price_buy, price_sell, weight_scu, timestamp = result

        # ✅ Create an embed message
        embed = discord.Embed(
            title=name,
            description="**Commodity Price Information**",
            color=discord.Color.blue()
        )
        embed.add_field(name="💰 Buy Price", value=f"{price_buy} aUEC", inline=True)
        embed.add_field(name="💵 Sell Price", value=f"{price_sell} aUEC", inline=True)
        embed.add_field(name="⚖️ Weight (SCU)", value=f"{weight_scu}", inline=False)
        embed.set_footer(text=f"Last updated: {timestamp}")

        # ✅ Use ctx.respond() instead of ctx.send()
        await ctx.respond(embed=embed)

    except Exception as e:
        await ctx.respond(f"❌ Error: {str(e)}")

# New command to find the best selling and buying locations for a commodity
@bot.slash_command(name="best_locations", description="Enter Commodity Name")
async def best_locations(
    ctx, 
    *,
    name: Option(str, "Choose a commodity", autocomplete=commodity_autocomplete)
):
    """Fetch the best buying and selling locations for a commodity"""
    try:
        # ✅ Defer response to prevent timeout
        await ctx.defer()

        prices_url = f"https://api.uexcorp.space/2.0/commodities_prices?commodity_name={name}"

        async with aiohttp.ClientSession() as session:
            async with session.get(prices_url) as response:
                if response.status != 200:
                    await ctx.respond(f"❌ API error: Unable to fetch data for {name}.")
                    return
                
                prices_data = await response.json()

        # ✅ Ensure valid API response
        if prices_data.get("status") != "ok" or not prices_data.get("data"):
            await ctx.respond(f"❌ No data found for {name}.")
            return

        best_sell, best_buy = None, None

        for location in prices_data["data"]:
            # Find the best selling location
            if location["price_sell"] > 0 and (not best_sell or location["price_sell"] > best_sell["price_sell"]):
                best_sell = location

            # Find the best buying location
            if location["price_buy"] > 0 and (not best_buy or location["price_buy"] < best_buy["price_buy"]):
                best_buy = location

        # ✅ Safely extract values
        def safe_get(data, key, default="N/A"):
            return data[key] if data and key in data else default

        sell_info = (
            f"**Terminal Name:** {safe_get(best_sell, 'terminal_name')}\n"
            f"**Location:** {safe_get(best_sell, 'city_name')}, {safe_get(best_sell, 'planet_name')}\n"
            f"**Price:** {safe_get(best_sell, 'price_sell')} UEC\n"
            f"**Faction:** {safe_get(best_sell, 'faction_name')}\n"
            f"**Star System:** {safe_get(best_sell, 'star_system_name')}"
        ) if best_sell else "No selling location available."

        buy_info = (
            f"**Terminal Name:** {safe_get(best_buy, 'terminal_name')}\n"
            f"**Location:** {safe_get(best_buy, 'city_name')}, {safe_get(best_buy, 'planet_name')}\n"
            f"**Price:** {safe_get(best_buy, 'price_buy')} UEC\n"
            f"**Faction:** {safe_get(best_buy, 'faction_name')}\n"
            f"**Star System:** {safe_get(best_buy, 'star_system_name')}"
        ) if best_buy else "No buying location available."

        # ✅ Embed response
        embed = discord.Embed(
            title=f"Best Locations for {name}",
            color=discord.Color.green()
        )
        embed.add_field(name="📈 Best Selling Location", value=sell_info, inline=False)
        embed.add_field(name="📉 Best Buying Location", value=buy_info, inline=False)

        # ✅ Use ctx.respond() to ensure bot replies
        await ctx.respond(embed=embed)

    except Exception as e:
        await ctx.respond(f"❌ Error: {str(e)}")


# New cargo manifest command with embedded output
@bot.slash_command(name="cargo_manifest", description="Enter Commodity Name and the Amount you have in SCU")
async def cargo_manifest(
    ctx, 
    name: Option(str, "Choose a commodity", autocomplete=commodity_autocomplete),
    amount_scu: int
):
    """Fetch the best selling price and location for a player's cargo manifest"""
    try:
        # ✅ Defer response to prevent timeout
        await ctx.defer()

        # ✅ Validate SCU input
        if amount_scu <= 0:
            await ctx.respond("❌ Amount of SCU must be greater than 0.")
            return

        # ✅ Corrected variable name from commodity_name → name
        prices_url = f"https://api.uexcorp.space/2.0/commodities_prices?commodity_name={name}"

        async with aiohttp.ClientSession() as session:
            async with session.get(prices_url) as response:
                if response.status != 200:
                    await ctx.respond(f"❌ API error: Unable to fetch data for {name}.")
                    return
                
                prices_data = await response.json()

        # ✅ Ensure valid API response
        if prices_data.get("status") != "ok" or not prices_data.get("data"):
            await ctx.respond(f"❌ No data found for {name}.")
            return

        best_sell = None
        for location in prices_data["data"]:
            if location["price_sell"] > 0 and (not best_sell or location["price_sell"] > best_sell["price_sell"]):
                best_sell = location

        # ✅ Ensure a valid selling location exists
        if best_sell:
            total_value = best_sell['price_sell'] * amount_scu
            embed = discord.Embed(
                title=f"Cargo Manifest for {name}",
                description=(
                    f"**Terminal Name:** {best_sell['terminal_name']}\n"
                    f"**Location:** {best_sell['city_name']}, {best_sell['planet_name']}\n"
                    f"**Price per SCU:** {best_sell['price_sell']} UEC\n"
                    f"**Total Value for {amount_scu} SCU:** {total_value} UEC\n"
                    f"**Faction:** {best_sell['faction_name']}\n"
                    f"**Star System:** {best_sell['star_system_name']}"
                ),
                color=discord.Color.purple()
            )
            await ctx.respond(embed=embed)
        else:
            await ctx.respond(f"❌ No valid selling location found for {name}.")

    except Exception as e:
        await ctx.respond(f"❌ Error: {str(e)}")

# Market Trends !market_trends
@bot.slash_command(name="market_trend", description="Show market trends (buy and sell) for a commodity over the last 7 days.")
async def market_trends(ctx: discord.ApplicationContext, 
                            commodity_name: Option(str, "Choose a commodity", autocomplete=commodity_autocomplete)):
    conn = sqlite3.connect('organizations.db')
    cursor = conn.cursor()

    # Fetch only the last 7 days of data
    cursor.execute("""
        SELECT timestamp, price_buy, price_sell 
        FROM commodity_prices 
        WHERE commodity_name = ? AND timestamp >= datetime('now', '-7 days')
        ORDER BY timestamp ASC
    """, (commodity_name,))
    
    data = cursor.fetchall()
    conn.close()

    if not data:
        await ctx.respond(f"❌ No data found for `{commodity_name}` in the last 7 days.")
        return

    # Convert to Pandas DataFrame for grouping by day
    df = pd.DataFrame(data, columns=["timestamp", "price_buy", "price_sell"])

    # Convert timestamps to date only (YYYY-MM-DD)
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.date

    # Group by date and get the average buy/sell prices for each day
    df = df.groupby("timestamp", as_index=False).mean()

    # Extract data for plotting
    timestamps = df["timestamp"].astype(str)  # Convert dates to strings for x-axis labels
    price_buy = df["price_buy"]
    price_sell = df["price_sell"]

    # Create the plot
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(timestamps, price_buy, label="Buy Price", color="green", marker="o", linestyle="--")
    ax.plot(timestamps, price_sell, label="Sell Price", color="red", marker="x", linestyle=":")

    # Formatting the x-axis
    plt.xticks(rotation=45, ha='right')
    plt.xlabel("Date")
    plt.ylabel("Price (UEC)")
    plt.title(f"Market Trend for {commodity_name} (Last 7 Days)")
    plt.legend()
    plt.grid()

    # Save the plot to a BytesIO object
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)  # Move to start of file for Discord to read

    # Send the plot as an image to Discord
    await ctx.respond(file=discord.File(buf, filename="market_trend.png"))

    # Clean up resources
    buf.close()
    plt.close(fig)

''' Comment out Organisation section for future use
# Command to create an organization
@bot.slash_command(name="create_org", description="Enter Organisation Name")
async def create_org(ctx, org_name: str, *, description: str):
    leader_id = ctx.author.id
    create_organization(org_name, description, leader_id)
    await ctx.send(f"✅ Organization `{org_name}` created successfully!")

# Command to join an organization
@bot.slash_command(name="join_org", description="Enter Organisation Name")
async def join_org(ctx, org_name: str):
    result = join_organization(ctx.author.id, org_name)
    await ctx.send(result)

# Command to award points to a member
@bot.slash_command(name="award_points", description="Discord name, Organisation name and point value")
async def award_points_command(ctx, member: discord.Member, org_name: str, points: int):
    result = award_points(ctx.author.id, member.id, org_name, points)
    await ctx.send(result)

# Command to leave an organization
@bot.slash_command(name="leave_org", description="Enter Org Name")
async def leave_org(ctx, org_name: str):
    result = leave_organization(ctx.author.id, org_name)
    await ctx.send(result)

# Org Info
@bot.slash_command(name="org_info", description="Displays information about an organization")
async def org_info(ctx: discord.ApplicationContext, org_name: str):
    conn = sqlite3.connect('organizations.db')
    cursor = conn.cursor()

    # Check if the organization exists
    cursor.execute("SELECT description FROM organizations WHERE org_name = ?", (org_name,))
    org_data = cursor.fetchone()
    if not org_data:
        conn.close()
        await ctx.respond(f"❌ Organization `{org_name}` does not exist.")
        return

    description = org_data[0]

    # Get the total number of members
    cursor.execute("SELECT COUNT(*) FROM members WHERE org_name = ?", (org_name,))
    total_members = cursor.fetchone()[0]

    # Get the leader (first member added, assuming they are the leader)
    cursor.execute("SELECT user_id FROM members WHERE org_name = ? ORDER BY rowid ASC LIMIT 1", (org_name,))
    leader_data = cursor.fetchone()
    leader_id = leader_data[0] if leader_data else "Unknown"

    # Get the member with the most points
    cursor.execute("SELECT user_id, MAX(points) FROM members WHERE org_name = ?", (org_name,))
    top_member_data = cursor.fetchone()
    top_member_id = top_member_data[0] if top_member_data and top_member_data[0] else "None"
    top_points = top_member_data[1] if top_member_data and top_member_data[1] is not None else 0

    conn.close()

    # Convert IDs to Discord mentions
    leader_mention = f"<@{leader_id}>" if leader_id != "Unknown" else "Unknown"
    top_member_mention = f"<@{top_member_id}>" if top_member_id != "None" else "None"

    # Create Embed
    embed = discord.Embed(title=f"📜 Organization Info: {org_name}", color=discord.Color.blue())
    embed.add_field(name="📖 Description", value=description, inline=False)
    embed.add_field(name="👥 Members", value=str(total_members), inline=True)
    embed.add_field(name="👑 Leader", value=leader_mention, inline=True)
    embed.add_field(name="🏆 Top Member", value=f"{top_member_mention} ({top_points} points)", inline=True)

    await ctx.respond(embed=embed)

    # Command to create a new role
@bot.slash_command(name="create_role", description="Create a custom role in your organization (Leader Only)")
async def create_role(ctx: discord.ApplicationContext, org_name: str, role_name: str):
    conn = sqlite3.connect("organizations.db")
    cursor = conn.cursor()
    
    # Check if the user is the leader by checking the 'leader_id' from the organizations table
    cursor.execute("SELECT leader_id FROM organizations WHERE org_name = ?", (org_name,))
    leader_data = cursor.fetchone()
    
    if not leader_data or leader_data[0] != ctx.author.id:
        await ctx.respond("❌ Only the organization leader can create roles.")
        conn.close()
        return
    
    # Insert the new role
    try:
        cursor.execute("INSERT INTO roles (org_name, role_name) VALUES (?, ?)", (org_name, role_name))
        conn.commit()
        await ctx.respond(f"✅ Role `{role_name}` created successfully in `{org_name}`!")
    except sqlite3.IntegrityError:
        await ctx.respond("❌ This role already exists in the organization.")
    
    conn.close()

# Command to assign a custom role
@bot.slash_command(name="assign_role", description="Assign a custom role to a member in your organization")
async def assign_role(ctx: discord.ApplicationContext, member: discord.Member, org_name: str, role_name: str):
    conn = sqlite3.connect("organizations.db")
    cursor = conn.cursor()
    
    # Check if the role exists in the organization
    cursor.execute("SELECT role_name FROM roles WHERE org_name = ? AND role_name = ?", (org_name, role_name))
    role_exists = cursor.fetchone()
    if not role_exists:
        await ctx.respond("❌ This role does not exist in the organization.")
        conn.close()
        return
    
    # Assign the role to the member
    cursor.execute("UPDATE members SET role = ? WHERE user_id = ? AND org_name = ?", (role_name, str(member.id), org_name))
    conn.commit()
    conn.close()
    
    await ctx.respond(f"✅ Assigned role `{role_name}` to {member.mention} in `{org_name}`.")

# Command to view roles in an organization
@bot.slash_command(name="org_roles", description="List all roles in an organization")
async def org_roles(ctx: discord.ApplicationContext, org_name: str):
    conn = sqlite3.connect("organizations.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT role_name FROM roles WHERE org_name = ?", (org_name,))
    roles = cursor.fetchall()
    conn.close()
    
    if not roles:
        await ctx.respond("❌ No roles found in this organization.")
        return
    
    role_list = "\n".join([role[0] for role in roles])
    await ctx.respond(f"📜 **Roles in {org_name}:**\n{role_list}")

# Set Income Share per role
@bot.slash_command(name="set_income_share", description="Set the income share percentage for a role (Leader Only)")
async def set_income_share(ctx: discord.ApplicationContext, org_name: str, role_name: str, income_share: float):
    if income_share < 0 or income_share > 100:
        await ctx.respond("❌ Income share must be between 0 and 100%.")
        return

    conn = sqlite3.connect("organizations.db")
    cursor = conn.cursor()

    # Verify if the user is the organization leader
    cursor.execute("SELECT leader_id FROM organizations WHERE org_name = ?", (org_name,))
    leader_data = cursor.fetchone()

    if not leader_data or leader_data[0] != ctx.author.id:
        await ctx.respond("❌ Only the organization leader can set income share percentages.")
        conn.close()
        return

    # Check if the role exists in the organization
    cursor.execute("SELECT role_name FROM roles WHERE org_name = ? AND role_name = ?", (org_name, role_name))
    role_exists = cursor.fetchone()

    if not role_exists:
        await ctx.respond("❌ This role does not exist in the organization.")
        conn.close()
        return

    # Update the income share for the role
    cursor.execute("UPDATE roles SET income_share = ? WHERE org_name = ? AND role_name = ?", (income_share, org_name, role_name))
    conn.commit()
    conn.close()

    await ctx.respond(f"✅ Set income share for `{role_name}` in `{org_name}` to {income_share}%.")

# Income Share Display
@bot.slash_command(name="income_shares", description="View the income share percentages for all roles in an organization")
async def income_shares(ctx: discord.ApplicationContext, org_name: str):
    conn = sqlite3.connect("organizations.db")
    cursor = conn.cursor()

    cursor.execute("SELECT role_name, income_share FROM roles WHERE org_name = ?", (org_name,))
    roles = cursor.fetchall()
    conn.close()

    if not roles:
        await ctx.respond("❌ No roles found in this organization.")
        return

    role_list = "\n".join([f"**{role[0]}** - {role[1]}%" for role in roles])
    await ctx.respond(f"📜 **Income Shares in {org_name}:**\n{role_list}")

# Distribute Income per role
@bot.slash_command(name="distribute_income", description="Distribute total income among members based on role shares (Leader Only)")
async def distribute_income(ctx: discord.ApplicationContext, org_name: str, total_income: float):
    if total_income <= 0:
        await ctx.respond("❌ Total income must be greater than 0.")
        return

    conn = sqlite3.connect("organizations.db")
    cursor = conn.cursor()

    # Verify if the user is the organization leader
    cursor.execute("SELECT leader_id FROM organizations WHERE org_name = ?", (org_name,))
    leader_data = cursor.fetchone()

    if not leader_data or leader_data[0] != ctx.author.id:
        await ctx.respond("❌ Only the organization leader can distribute income.")
        conn.close()
        return

    # Get all members and their assigned roles
    cursor.execute("SELECT user_id, role FROM members WHERE org_name = ?", (org_name,))
    members = cursor.fetchall()

    if not members:
        await ctx.respond("❌ No members found in this organization.")
        conn.close()
        return

    # Get role income shares
    cursor.execute("SELECT role_name, income_share FROM roles WHERE org_name = ?", (org_name,))
    role_shares = {role: share for role, share in cursor.fetchall()}

    conn.close()

    # Calculate total share percentage assigned
    total_assigned_share = sum(role_shares.get(member[1], 0) for member in members)

    if total_assigned_share == 0:
        await ctx.respond("❌ No valid income shares found for roles.")
        return

    # Calculate individual payouts
    payouts = {}
    for user_id, role in members:
        role_share = role_shares.get(role, 0)
        if role_share > 0:
            payouts[user_id] = (role_share / total_assigned_share) * total_income

    # Generate output message
    payout_message = "\n".join([f"<@{user_id}> receives **${amount:.2f}**" for user_id, amount in payouts.items()])

    await ctx.respond(f"📢 **Income Distribution for `{org_name}`:**\n{payout_message}")
Comment out Organisation section for future use''' 
bot.run(TOKEN)