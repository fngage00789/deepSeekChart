import discord
from discord.ext import commands, tasks
import yfinance as yf
import datetime
import matplotlib.pyplot as plt
import io
import os
import asyncio
from matplotlib.ticker import MaxNLocator
from discord.utils import get
from dotenv import load_dotenv
import pandas as pd
import numpy as np
from textblob import TextBlob
import requests
from bs4 import BeautifulSoup
from flask import Flask
from threading import Thread

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

if not DISCORD_TOKEN:
    raise ValueError(
        "No Discord token found. Please set DISCORD_TOKEN in your .env file")

# Flask server setup for keep_alive
app = Flask('')


@app.route('/')
def home():
    return "Discord Bot is Alive!"


def run():
    app.run(host='0.0.0.0', port=8080)


def keep_alive():
    t = Thread(target=run)
    t.start()


# Start the keep_alive server
keep_alive()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Symbols to track with full names
symbols = {'NAS100': '^NDX', 'Gold': 'GC=F'}

# Chart colors
COLORS = {
    'up': '#4CAF50',  # Green
    'down': '#F44336',  # Red
    'volume': '#2196F3',  # Blue
    'neutral': '#FFC107',  # Yellow
    'impact_high': '#FF5722',  # Deep Orange
    'impact_medium': '#FF9800',  # Orange
    'impact_low': '#FFC107'  # Amber
}

# Server data storage
server_data = {}


class ServerData:

    def __init__(self):
        self.channel_id = None
        self.auto_update = False


def fetch_market_sentiment():
    """Fetch market sentiment from Forex Factory news and calendar"""
    try:
        url = "https://www.forexfactory.com/"
        headers = {
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')

        events = []
        calendar = soup.find('table', class_='calendar__table')

        if calendar:
            for row in calendar.find_all('tr', class_='calendar__row'):
                if 'calendar__row--header' in row.get('class', []):
                    continue

                event = {
                    'time':
                    row.find('td',
                             class_='calendar__time').get_text(strip=True),
                    'currency':
                    row.find('td',
                             class_='calendar__currency').get_text(strip=True),
                    'impact':
                    row.find('td', class_='calendar__impact').find(
                        'span')['title'].lower()
                    if row.find('td', class_='calendar__impact').find('span')
                    else 'low',
                    'event':
                    row.find('td',
                             class_='calendar__event').get_text(strip=True),
                    'actual':
                    row.find('td',
                             class_='calendar__actual').get_text(strip=True),
                    'forecast':
                    row.find('td',
                             class_='calendar__forecast').get_text(strip=True),
                    'previous':
                    row.find('td',
                             class_='calendar__previous').get_text(strip=True)
                }

                if event['impact'] in ['high', 'medium']:
                    events.append(event)

        sentiment_score = 0
        for event in events:
            try:
                actual = float(event['actual'])
                forecast = float(event['forecast'])
                sentiment_score += (
                    actual - forecast) / forecast if forecast != 0 else 0
            except (ValueError, TypeError):
                continue

        avg_sentiment = np.clip(sentiment_score / len(events) if events else 0,
                                -1, 1)

        return {
            'events': events[:5],
            'sentiment': avg_sentiment,
            'bullish': avg_sentiment > 0.1,
            'bearish': avg_sentiment < -0.1,
            'impact_events': len([e for e in events if e['impact'] == 'high'])
        }
    except Exception as e:
        print(f"Error fetching Forex Factory sentiment: {e}")
        return None


def create_nas100_chart(symbol_name,
                        symbol_data,
                        history,
                        sentiment_data=None):
    """Create an advanced NAS100 futures chart with technical indicators and sentiment"""
    plt.style.use('dark_background')
    fig, (ax1, ax2,
          ax3) = plt.subplots(3,
                              1,
                              figsize=(12, 10),
                              gridspec_kw={'height_ratios': [3, 1, 1]},
                              sharex=True)

    # Calculate technical indicators
    prices = history['Close']
    sma20 = prices.rolling(window=20).mean()
    sma50 = prices.rolling(window=50).mean()
    rolling_std = prices.rolling(window=20).std()
    upper_band = sma20 + (2 * rolling_std)
    lower_band = sma20 - (2 * rolling_std)

    # Price chart
    ax1.plot(history.index, prices, label='Price', color='white', linewidth=2)
    ax1.plot(history.index,
             sma20,
             label='20-SMA',
             color='#FF9800',
             linestyle='--')
    ax1.plot(history.index,
             sma50,
             label='50-SMA',
             color='#9C27B0',
             linestyle='--')
    ax1.fill_between(history.index,
                     upper_band,
                     lower_band,
                     color='#3F51B5',
                     alpha=0.2)

    if sentiment_data:
        sentiment_color = COLORS['up'] if sentiment_data['bullish'] else (
            COLORS['down'] if sentiment_data['bearish'] else COLORS['neutral'])
        ax1.axhspan(prices.min(),
                    prices.max(),
                    facecolor=sentiment_color,
                    alpha=0.1)

        if sentiment_data.get('impact_events', 0) > 0:
            ax1.annotate(
                f"⚠️ {sentiment_data['impact_events']} High Impact Events",
                xy=(0.02, 0.95),
                xycoords='axes fraction',
                color=COLORS['impact_high'],
                fontsize=10)

    ax1.set_title(f'{symbol_name} Futures - Advanced Analysis', pad=20)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Volume chart
    ax2.bar(history.index,
            history['Volume'],
            color=COLORS['volume'],
            alpha=0.7)
    ax2.set_ylabel('Volume')
    ax2.grid(True, alpha=0.3)

    # RSI indicator
    delta = prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rsi = 100 - (100 / (1 + (avg_gain / avg_loss)))

    ax3.plot(history.index, rsi, label='RSI', color='#00BCD4', linewidth=2)
    ax3.axhline(70, color=COLORS['down'], linestyle='--', alpha=0.7)
    ax3.axhline(30, color=COLORS['up'], linestyle='--', alpha=0.7)
    ax3.set_ylabel('RSI')
    ax3.grid(True, alpha=0.3)

    plt.xticks(rotation=45)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf


async def send_market_update(channel, symbol_name, symbol):
    """Send advanced market data for a specific symbol to a channel"""
    try:
        data = yf.Ticker(symbol)
        hist = data.history(period='2d', interval='15m')

        if hist.empty:
            return False

        sentiment_data = fetch_market_sentiment(
        ) if symbol_name == 'NAS100' else None
        chart = create_nas100_chart(symbol_name, symbol, hist, sentiment_data)

        await channel.send(file=discord.File(
            chart, filename=f"{symbol_name.replace('/', '_')}_chart.png"))

        latest = hist.iloc[-1]
        prev_close = hist.iloc[-2]['Close'] if len(
            hist) > 1 else latest['Close']
        change = latest['Close'] - prev_close
        pct_change = (change / prev_close) * 100

        # Calculate technical indicators
        delta = hist['Close'].diff()
        avg_gain = delta.where(delta > 0, 0).rolling(window=14).mean().iloc[-1]
        avg_loss = -delta.where(delta < 0,
                                0).rolling(window=14).mean().iloc[-1]
        rsi = 100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss != 0 else 0

        sma20 = hist['Close'].rolling(window=20).mean().iloc[-1]
        rolling_std = hist['Close'].rolling(window=20).std().iloc[-1]
        bb_status = "Near Upper Band" if latest['Close'] > sma20 + (
            1.9 * rolling_std) else (
                "Near Lower Band" if latest['Close'] < sma20 -
                (1.9 * rolling_std) else "Mid Range")

        embed = discord.Embed(
            title=f"{symbol_name} Market Analysis",
            description=
            f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            color=0x00ff00 if change >= 0 else 0xff0000)

        embed.add_field(name="Price",
                        value=f"${latest['Close']:.2f}",
                        inline=True)
        embed.add_field(name="Change",
                        value=f"{change:+.2f} ({pct_change:+.2f}%)",
                        inline=True)
        embed.add_field(name="RSI (14)", value=f"{rsi:.2f}", inline=True)
        embed.add_field(name="Bollinger Bands", value=bb_status, inline=True)

        if symbol_name == 'NAS100' and sentiment_data:
            sentiment_status = "Bullish 🚀" if sentiment_data['bullish'] else (
                "Bearish 🐻" if sentiment_data['bearish'] else "Neutral ⚖️")
            embed.add_field(name="Sentiment",
                            value=sentiment_status,
                            inline=True)
            embed.add_field(name="Impact Events",
                            value=sentiment_data.get('impact_events', 0),
                            inline=True)

        embed.add_field(
            name="Range",
            value=f"${hist['Low'].min():.2f} - ${hist['High'].max():.2f}",
            inline=True)
        embed.add_field(name="Volume",
                        value=f"{latest['Volume']:,.0f}",
                        inline=True)

        await channel.send(embed=embed)
        return True

    except Exception as e:
        print(f"Error fetching {symbol_name}: {e}")
        await channel.send(f"❌ Could not retrieve data for {symbol_name}")
        return False


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    for guild in bot.guilds:
        server_data[guild.id] = ServerData()
    if not auto_update.is_running():
        auto_update.start()


@bot.command()
@commands.has_permissions(administrator=True)
async def setupchannel(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    server_data[ctx.guild.id].channel_id = channel.id
    await ctx.send(f"✅ Market updates will be posted in {channel.mention}")


@bot.command()
@commands.has_permissions(administrator=True)
async def toggleauto(ctx):
    server_data[
        ctx.guild.id].auto_update = not server_data[ctx.guild.id].auto_update
    status = "ON" if server_data[ctx.guild.id].auto_update else "OFF"
    await ctx.send(f"✅ Automatic updates are now {status}")


@bot.command()
async def market(ctx, symbol_name: str = None):
    if symbol_name:
        symbol_found = next(
            ((n, s)
             for n, s in symbols.items() if symbol_name.lower() in n.lower()),
            None)
        if symbol_found:
            await send_market_update(ctx.channel, *symbol_found)
        else:
            await ctx.send(
                f"❌ Symbol not found. Available: {', '.join(symbols.keys())}")
    else:
        for name, symbol in symbols.items():
            await send_market_update(ctx.channel, name, symbol)


@tasks.loop(minutes=15)
async def auto_update():
    for guild_id, data in server_data.items():
        if data.auto_update and data.channel_id:
            channel = bot.get_channel(data.channel_id)
            if channel:
                for name, symbol in symbols.items():
                    await send_market_update(channel, name, symbol)


try:
    bot.run(DISCORD_TOKEN)
except Exception as e:
    print(f"Error starting bot: {e}")
