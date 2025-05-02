import discord
from discord.ext import commands, tasks
import yfinance as yf
import datetime
import matplotlib.pyplot as plt
import io
import os
import asyncio
from matplotlib.ticker import MaxNLocator
from dotenv import load_dotenv
import pandas as pd
import numpy as np
from textblob import TextBlob
import requests
from bs4 import BeautifulSoup
import json
import logging
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger('discord')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

if not DISCORD_TOKEN:
    logger.critical("No DISCORD_TOKEN found in .env file")
    raise ValueError("Missing Discord token")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None
)

# Symbols to track
symbols = {'NAS100': '^NDX', 'Gold': 'GC=F'}

# Chart colors
COLORS = {
    'up': '#4CAF50',
    'down': '#F44336',
    'volume': '#2196F3',
    'neutral': '#FFC107',
    'impact_high': '#FF5722'
}

# Server data persistence
class ServerData:
    def __init__(self, channel_id=None, auto_update=False):
        self.channel_id = channel_id
        self.auto_update = auto_update

def save_data():
    """Save server data to JSON file"""
    with open('server_data.json', 'w') as f:
        json.dump(
            {guild_id: vars(data) for guild_id, data in server_data.items()},
            f
        )

def load_data():
    """Load server data from JSON file"""
    try:
        with open('server_data.json', 'r') as f:
            data = json.load(f)
            return {int(guild_id): ServerData(**values) for guild_id, values in data.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

server_data = load_data()

# Market data functions
def fetch_market_sentiment():
    """Fetch market sentiment from Forex Factory"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get("https://www.forexfactory.com/", headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        events = []
        for row in soup.find_all('tr', class_='calendar__row'):
            if 'calendar__row--header' in row.get('class', []):
                continue
                
            event = {
                'time': row.find('td', class_='calendar__time').get_text(strip=True),
                'impact': row.find('td', class_='calendar__impact').find('span')['title'].lower() 
                         if row.find('td', class_='calendar__impact').find('span') else 'low'
            }
            if event['impact'] in ['high', 'medium']:
                events.append(event)
                
        return {
            'impact_events': len([e for e in events if e['impact'] == 'high'])
        }
        
    except Exception as e:
        logger.error(f"Error fetching sentiment: {str(e)}")
        return None

def create_chart(symbol_name, history, sentiment_data=None):
    """Generate market chart with technical indicators"""
    try:
        plt.style.use('dark_background')
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10), gridspec_kw={'height_ratios': [3, 1, 1]})
        
        # Price chart
        prices = history['Close']
        sma20 = prices.rolling(20).mean()
        sma50 = prices.rolling(50).mean()
        
        ax1.plot(history.index, prices, label='Price', color='white', linewidth=2)
        ax1.plot(history.index, sma20, label='20-SMA', color='#FF9800', linestyle='--')
        ax1.plot(history.index, sma50, label='50-SMA', color='#9C27B0', linestyle='--')
        
        # RSI
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        rsi = 100 - (100 / (1 + (gain.rolling(14).mean() / loss.rolling(14).mean())))
        
        ax3.plot(history.index, rsi, color='#00BCD4')
        ax3.axhline(70, color=COLORS['down'], linestyle='--')
        ax3.axhline(30, color=COLORS['up'], linestyle='--')
        
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()
        return buf
        
    except Exception as e:
        logger.error(f"Chart error: {str(e)}")
        raise

async def send_market_update(channel, symbol_name, symbol):
    """Send market update to specified channel"""
    try:
        data = yf.Ticker(symbol)
        hist = data.history(period='2d', interval='15m')
        
        if hist.empty:
            await channel.send(f"❌ No data for {symbol_name}")
            return False
            
        chart = create_chart(symbol_name, hist)
        await channel.send(
            file=discord.File(chart, f"{symbol_name}_chart.png"),
            embed=discord.Embed(
                title=f"{symbol_name} Market Update",
                description=f"Last update: {datetime.datetime.now().strftime('%H:%M:%S')}",
                color=0x00ff00 if hist['Close'][-1] > hist['Close'][-2] else 0xff0000
            ).add_field(
                name="Price",
                value=f"${hist['Close'][-1]:.2f}",
                inline=True
            )
        )
        return True
        
    except Exception as e:
        logger.error(f"Market update failed: {str(e)}")
        await channel.send(f"❌ Error updating {symbol_name}")
        return False

# Bot commands
@bot.command()
@commands.has_permissions(administrator=True)
async def setupchannel(ctx, channel: discord.TextChannel = None):
    """Set the channel for automatic updates"""
    channel = channel or ctx.channel
    server_data[ctx.guild.id] = ServerData(channel.id, False)
    save_data()
    await ctx.send(f"✅ Updates will be posted in {channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def toggleauto(ctx):
    """Toggle automatic updates"""
    server = server_data[ctx.guild.id]
    server.auto_update = not server.auto_update
    save_data()
    await ctx.send(f"✅ Automatic updates {'ENABLED' if server.auto_update else 'DISABLED'}")

@bot.command()
async def market(ctx, symbol_name: str = None):
    """Manual market update"""
    if symbol_name:
        symbol = symbols.get(symbol_name.title())
        if symbol:
            await send_market_update(ctx.channel, symbol_name, symbol)
        else:
            await ctx.send(f"❌ Invalid symbol. Options: {', '.join(symbols.keys())}")
    else:
        for name, symbol in symbols.items():
            await send_market_update(ctx.channel, name, symbol)

# Automatic updates
@tasks.loop(minutes=15)
async def auto_update():
    """Automatic market updates every 15 minutes"""
    logger.info("Running auto-update")
    for guild_id, data in server_data.items():
        if data.auto_update and data.channel_id:
            channel = bot.get_channel(data.channel_id)
            if channel:
                for name, symbol in symbols.items():
                    await send_market_update(channel, name, symbol)

# Bot events
@bot.event
async def on_ready():
    """Initialize when bot starts"""
    logger.info(f"Logged in as {bot.user.name}")
    
    # Initialize missing guilds
    for guild in bot.guilds:
        if guild.id not in server_data:
            server_data[guild.id] = ServerData()
    
    # Start auto-update task
    if not auto_update.is_running():
        auto_update.start()
        logger.info("Auto-update task started")

@bot.event
async def on_guild_join(guild):
    """Initialize data for new servers"""
    server_data[guild.id] = ServerData()
    save_data()

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need administrator permissions for this command")
    else:
        logger.error(f"Command error: {str(error)}")
        await ctx.send("❌ An error occurred")

# Run the bot
if __name__ == "__main__":
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.critical(f"Bot crashed: {str(e)}")

