import discord
from discord.ext import commands
import aiohttp
from bs4 import BeautifulSoup
import datetime
from typing import List, Dict

class ForexFactoryCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.base_url = "https://www.forexfactory.com/calendar"
    
    async def fetch_calendar_data(self) -> BeautifulSoup:
        """Fetch and parse the Forex Factory calendar page"""
        try:
            async with self.session.get(self.base_url) as response:
                if response.status == 200:
                    html = await response.text()
                    return BeautifulSoup(html, 'html.parser')
                return None
        except Exception as e:
            print(f"Error fetching ForexFactory data: {e}")
            return None
    
    def filter_events(self, soup: BeautifulSoup, asset_filter: str) -> List[Dict]:
        """Filter events based on asset type (gold, nas100, forex)"""
        events = []
        calendar_table = soup.find(id="calendarTable")
        
        if not calendar_table:
            return events
            
        for row in calendar_table.find_all("tr", class_="calendar__row"):
            if not row.get('data-eventid'):
                continue  # Skip header rows
            
            # Extract basic event info
            time = row.find("td", class_="time").get_text(strip=True)
            currency = row.find("td", class_="currency").get_text(strip=True)
            title = row.find("td", class_="event").get_text(strip=True)
            
            # Get impact level (high/medium/low)
            impact_cell = row.find("td", class_="impact")
            impact = impact_cell.find("span")["class"][0].replace("icon--", "") if impact_cell else "low"
            
            # Get actual/forecast/previous values
            actual = row.find("td", class_="actual").get_text(strip=True)
            forecast = row.find("td", class_="forecast").get_text(strip=True)
            previous = row.find("td", class_="previous").get_text(strip=True)
            
            # Apply filters based on asset type
            if asset_filter == "gold":
                if "XAU" not in currency:
                    continue
            elif asset_filter == "nas100":
                if not any(x in title.upper() for x in ["NASDAQ", "NQ", "TECH", "STOCKS", "EQUITIES"]):
                    continue
            elif asset_filter == "forex":
                if currency not in ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]:
                    continue
            
            events.append({
                "time": time,
                "currency": currency,
                "title": title,
                "impact": impact,
                "actual": actual,
                "forecast": forecast,
                "previous": previous
            })
        
        return events
    
    @commands.command(name='gold')
    async def gold_news(self, ctx):
        """Get current gold (XAU) market news from ForexFactory"""
        await ctx.trigger_typing()
        
        soup = await self.fetch_calendar_data()
        if not soup:
            return await ctx.send("❌ Failed to fetch data from ForexFactory")
        
        events = self.filter_events(soup, "gold")
        
        if not events:
            return await ctx.send("ℹ️ No gold-related news found for today")
        
        for event in events[:5]:  # Limit to 5 events to avoid spam
            embed = self.create_embed(event, "🟠 Gold (XAU) Market News")
            await ctx.send(embed=embed)
    
    @commands.command(name='nas100')
    async def nas100_news(self, ctx):
        """Get current NAS100 market news from ForexFactory"""
        await ctx.trigger_typing()
        
        soup = await self.fetch_calendar_data()
        if not soup:
            return await ctx.send("❌ Failed to fetch data from ForexFactory")
        
        events = self.filter_events(soup, "nas100")
        
        if not events:
            return await ctx.send("ℹ️ No NAS100-related news found for today")
        
        for event in events[:5]:
            embed = self.create_embed(event, "🔵 NAS100 Market News")
            await ctx.send(embed=embed)
    
    @commands.command(name='forex')
    async def forex_news(self, ctx):
        """Get current Forex market news from ForexFactory"""
        await ctx.trigger_typing()
        
        soup = await self.fetch_calendar_data()
        if not soup:
            return await ctx.send("❌ Failed to fetch data from ForexFactory")
        
        events = self.filter_events(soup, "forex")
        
        if not events:
            return await ctx.send("ℹ️ No major forex news found for today")
        
        for event in events[:5]:
            embed = self.create_embed(event, "💱 Forex Market News")
            await ctx.send(embed=embed)
    
    def create_embed(self, event: Dict, title: str) -> discord.Embed:
        """Create a Discord embed from event data"""
        color_map = {
            "high": 0xFF0000,    # Red
            "medium": 0xFFA500,  # Orange
            "low": 0xFFFF00      # Yellow
        }
        
        embed = discord.Embed(
            title=f"{title} - {event['currency']}",
            description=event["title"],
            color=color_map.get(event["impact"], 0x000000),
            timestamp=datetime.datetime.now()
        )
        
        embed.add_field(name="🕒 Time", value=event["time"], inline=True)
        embed.add_field(name="⚡ Impact", value=event["impact"].capitalize(), inline=True)
        
        if event["actual"]:
            embed.add_field(name="📊 Actual", value=event["actual"], inline=True)
            embed.add_field(name="🔮 Forecast", value=event["forecast"], inline=True)
            embed.add_field(name="📅 Previous", value=event["previous"], inline=True)
        else:
            embed.add_field(name="⏳ Scheduled", value=event["time"], inline=False)
            embed.add_field(name="🔮 Forecast", value=event["forecast"], inline=True)
            embed.add_field(name="📅 Previous", value=event["previous"], inline=True)
        
        embed.set_footer(text="Data from ForexFactory", icon_url="https://www.forexfactory.com/favicon.ico")
        return embed

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        asyncio.create_task(self.session.close())

def setup(bot):
    bot.add_cog(ForexFactoryCommands(bot))
