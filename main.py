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
from cachetools import TTLCache

# ======================
# CONFIGURATION
# ======================
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    raise ValueError("Missing Discord token in environment variables")

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

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None
)

# Market symbols and cache
symbols = {'NAS100': '^NDX', 'Gold': 'GC=F'}
data_cache = TTLCache(maxsize=100, ttl=1800)  # 30 minute cache

# Chart styling
COLORS = {
    'up': '#4CAF50',
    'down': '#F44336',
    'volume': '#2196F3',
    'neutral': '#FFC107',
    'impact_high': '#FF5722'
}

# ======================
# DATA PERSISTENCE
# ======================
class ServerData:
    def __init__(self, channel_id=None, auto_update=False):
        self.channel_id = channel_id
        self.auto_update = auto_update

def save_data():
    """Save server data to JSON file"""
    try:
        with open('server_data.json', 'w') as f:
            json.dump(
                {guild_id: vars(data) for guild_id, data in server_data.items()},
                f
            )
    except Exception as e:
        logger.error(f"Error saving data: {str(e)}")

def load_data():
    """Load server data from JSON file"""
    try:
        with open('server_data.json', 'r') as f:
            data = json.load(f)
            return {int(guild_id): ServerData(**values) for guild_id, values in data.items()}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Loading fresh data: {str(e)}")
        return {}

server_data = load_data()

# ======================
# MARKET DATA FUNCTIONS
# ======================
async def fetch_with_retry(ticker_symbol, retries=3, delay=1):
    """Fetch stock data with retry logic"""
    for attempt in range(retries):
        try:
            if ticker_symbol in data_cache:
                logger.debug(f"Using cached data for {ticker_symbol}")
                return data_cache[ticker_symbol]
                
            logger.info(f"Fetching fresh data for {ticker_symbol} (attempt {attempt + 1})")
            data = yf.Ticker(ticker_symbol)
            hist = data.history(period='2d', interval='15m')
            
            if hist.empty:
                raise ValueError("Empty data returned")
                
            data_cache[ticker_symbol] = hist
            return hist
            
        except Exception as e:
            if attempt == retries - 1:
                raise
            await asyncio.sleep(delay * (attempt + 1))
            continue

async def fetch_market_sentiment():
    """Fetch market sentiment from Forex Factory with error handling"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with requests.Session() as session:
            response = await session.get(
                "https://www.forexfactory.com/",
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            
        soup = BeautifulSoup(response.text, 'html.parser')
        events = []
        
        for row in soup.find_all('tr', class_='calendar__row'):
            if 'calendar__row--header' in row.get('class', []):
                continue
                
            impact = row.find('td', class_='calendar__impact')
            if impact and impact.find('span'):
                event_impact = impact.find('span')['title'].lower()
                if event_impact in ['high', 'medium']:
                    events.append({
                        'time': row.find('td', class_='calendar__time').get_text(strip=True),
                        'impact': event_impact
                    })
                    
        return {
            'high_impact_events': len([e for e in events if e['impact'] == 'high']),
            'total_events': len(events)
        }
        
    except Exception as e:
        logger.error(f"Sentiment fetch error: {str(e)}")
        return None

def create_chart(symbol_name, history):
    """Generate professional trading chart with error handling"""
    try:
        plt.style.use('dark_background')
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]})
        
        # Main price chart
        prices = history['Close']
        ax1.plot(history.index, prices, label='Price', color='white', linewidth=2)
        
        # Add moving averages
        for period, color in [(20, '#FF9800'), (50, '#9C27B0')]:
            sma = prices.rolling(period).mean()
            ax1.plot(history.index, sma, label=f'{period}-SMA', color=color, linestyle='--')
        
        # Volume chart
        ax2.bar(history.index, history['Volume'], color=COLORS['volume'], alpha=0.7)
        
        # Formatting
        ax1.legend()
        ax1.set_title(f'{symbol_name} Price Analysis')
        ax2.set_title('Trading Volume')
        plt.tight_layout()
        
        # Save to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        return buf
        
    except Exception as e:
        logger.error(f"Chart generation failed: {str(e)}")
        raise

# ======================
# BOT COMMANDS
# ======================
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
    if ctx.guild.id not in server_data:
        server_data[ctx.guild.id] = ServerData()
        
    server_data[ctx.guild.id].auto_update = not server_data[ctx.guild.id].auto_update
    save_data()
    await ctx.send(f"✅ Automatic updates {'ENABLED' if server_data[ctx.guild.id].auto_update else 'DISABLED'}")

@bot.command()
async def market(ctx, symbol_name: str = None):
    """Get current market data"""
    try:
        if symbol_name:
            symbol = symbols.get(symbol_name.title())
            if not symbol:
                return await ctx.send(f"❌ Invalid symbol. Options: {', '.join(symbols.keys())}")
            await send_market_update(ctx.channel, symbol_name, symbol)
        else:
            for name, symbol in symbols.items():
                await send_market_update(ctx.channel, name, symbol)
                await asyncio.sleep(1)  # Rate limiting
    except Exception as e:
        logger.error(f"Market command error: {str(e)}")
        await ctx.send("❌ Failed to fetch market data")

# ======================
# CORE FUNCTIONALITY
# ======================
async def send_market_update(channel, symbol_name, symbol):
    """Send comprehensive market update"""
    try:
        hist = await fetch_with_retry(symbol)
        if hist is None:
            return False
            
        # PROPER pandas indexing using .iloc
        current_price = hist['Close'].iloc[-1]
        prev_price = hist['Close'].iloc[-2]
        price_change = ((current_price - prev_price) / prev_price) * 100
        
        chart = create_chart(symbol_name, hist)
        sentiment = await fetch_market_sentiment()
        
        embed = discord.Embed(
            title=f"{symbol_name} Market Update",
            description=f"Last update: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            color=COLORS['up'] if current_price > prev_price else COLORS['down']
        )
        
        embed.add_field(name="Current Price", value=f"${current_price:.2f}", inline=True)
        embed.add_field(name="24h Change", value=f"{price_change:.2f}%", inline=True)
        
        if sentiment:
            embed.add_field(
                name="Market Sentiment",
                value=f"{sentiment['high_impact_events']} high impact events today",
                inline=False
            )
        
        file = discord.File(chart, filename=f"{symbol_name}_chart.png")
        embed.set_image(url=f"attachment://{symbol_name}_chart.png")
        
        await channel.send(file=file, embed=embed)
        return True
        
    except Exception as e:
        logger.error(f"Update failed for {symbol_name}: {str(e)}")
        await channel.send(f"❌ Failed to update {symbol_name}")
        return False

# ======================
# TASKS AND EVENTS
# ======================
@tasks.loop(minutes=15)
async def auto_update():
    """Automatic market updates"""
    logger.info("Executing auto-update")
    for guild_id, data in server_data.items():
        if data.auto_update and data.channel_id:
            channel = bot.get_channel(data.channel_id)
            if channel:
                try:
                    for name, symbol in symbols.items():
                        await send_market_update(channel, name, symbol)
                        await asyncio.sleep(2)  # Rate limiting
                except Exception as e:
                    logger.error(f"Auto-update error for guild {guild_id}: {str(e)}")

@bot.event
async def on_ready():
    """Initialize bot"""
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    
    # Initialize missing guilds
    for guild in bot.guilds:
        if guild.id not in server_data:
            server_data[guild.id] = ServerData()
            logger.info(f"Initialized new guild: {guild.name}")
    
    save_data()
    
    if not auto_update.is_running():
        auto_update.start()
        logger.info("Started auto-update task")

@bot.event
async def on_guild_join(guild):
    """Handle new guilds"""
    server_data[guild.id] = ServerData()
    save_data()
    logger.info(f"Joined new guild: {guild.name}")

@bot.event
async def on_command_error(ctx, error):
    """Error handling"""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need administrator permissions for this command")
    else:
        logger.error(f"Command error: {str(error)}", exc_info=True)
        await ctx.send("❌ An error occurred executing that command")

# ======================
# START BOT
# ======================
if __name__ == "__main__":
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.critical(f"Bot crashed: {str(e)}", exc_info=True)