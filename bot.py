import os
import json
import requests
import asyncio
import aiohttp
import random
import time
from datetime import datetime, timedelta
from telegram import Bot, InputMediaPhoto
from telegram.error import TelegramError
import logging
from bs4 import BeautifulSoup
import re
import hashlib

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID', '@smartdealsindia5')
AFFILIATE_TAG = os.getenv('AFFILIATE_TAG', 'smartdeals063-21')

class SmartDealsBot:
    def __init__(self):
        self.bot = Bot(token=BOT_TOKEN)
        self.session = None
        self.posted_products = set()
        self.deal_tracker = {}
        self.load_tracker()
        
        # All categories to search
        self.categories = [
            'electronics', 'mobiles', 'laptops', 'headphones', 'speakers',
            'watches', 'cameras', 'home-kitchen', 'furniture', 'decor',
            'clothing', 'shoes', 'bags', 'beauty', 'health',
            'books', 'toys', 'sports', 'fitness', 'automotive',
            'tools', 'garden', 'pet-supplies', 'grocery', 'stationery'
        ]
        
        # Price ranges for deals (in INR)
        self.price_ranges = [
            (100, 500),    # Budget deals
            (500, 1000),   # Value deals
            (1000, 2000),  # Mid-range
            (2000, 5000)   # Premium deals
        ]
        
    def load_tracker(self):
        """Load tracking data"""
        try:
            with open('deal_tracker.json', 'r') as f:
                data = json.load(f)
                self.posted_products = set(data.get('posted', []))
                self.deal_tracker = data.get('tracker', {})
        except FileNotFoundError:
            self.posted_products = set()
            self.deal_tracker = {}
    
    def save_tracker(self):
        """Save tracking data"""
        data = {
            'posted': list(self.posted_products),
            'tracker': self.deal_tracker,
            'last_updated': datetime.now().isoformat()
        }
        with open('deal_tracker.json', 'w') as f:
            json.dump(data, f, indent=2)
    
    async def create_session(self):
        """Create HTTP session"""
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0'
        })
    
    async def close_session(self):
        """Close session"""
        if self.session:
            await self.session.close()
    
    def generate_product_hash(self, title, price):
        """Generate unique hash for product"""
        text = f"{title}_{price}"
        return hashlib.md5(text.encode()).hexdigest()[:12]
    
    def generate_amazon_link(self, asin):
        """Generate 100% working Amazon link"""
        # Multiple link formats to ensure working link
        base_urls = [
            f"https://www.amazon.in/dp/{asin}?tag={AFFILIATE_TAG}",
            f"https://www.amazon.in/gp/product/{asin}?tag={AFFILIATE_TAG}",
            f"https://amzn.in/d/{asin}?tag={AFFILIATE_TAG}"
        ]
        return base_urls[0]  # Using primary format
    
    def clean_price(self, price_text):
        """Clean and convert price text to float"""
        if not price_text:
            return 0
        
        # Remove currency symbols and commas
        clean = re.sub(r'[^\d.]', '', price_text)
        try:
            return float(clean)
        except:
            return 0
    
    async def search_amazon_deals(self, category, min_price=100, max_price=5000, pages=2):
        """Search Amazon for deals in specific category and price range"""
        deals = []
        
        for page in range(1, pages + 1):
            # Construct search URL with filters
            search_url = (
                f"https://www.amazon.in/s?"
                f"k={category.replace('-', '+')}"
                f"&rh=p_36%3A{int(min_price)}00-{int(max_price)}00"
                f"&s=price-desc-rank"  # Sort by price (low to high)
                f"&page={page}"
                f"&ref=sr_pg_{page}"
            )
            
            try:
                async with self.session.get(search_url, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        page_deals = await self.parse_search_results(html, category)
                        deals.extend(page_deals)
                        
                        # Delay between requests
                        await asyncio.sleep(random.uniform(2, 4))
                        
            except Exception as e:
                logger.error(f"Error searching {category}: {e}")
                continue
        
        return deals
    
    async def parse_search_results(self, html, category):
        """Parse Amazon search results page"""
        deals = []
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find all product containers
        products = soup.find_all('div', {'data-component-type': 's-search-result'})
        
        for product in products:
            try:
                # Extract ASIN
                asin = product.get('data-asin')
                if not asin:
                    continue
                
                # Generate product hash
                title_elem = product.find('h2')
                if not title_elem:
                    continue
                    
                title = title_elem.text.strip()[:150]
                
                # Skip if already posted
                product_hash = self.generate_product_hash(title, asin)
                if product_hash in self.posted_products:
                    continue
                
                # Extract price
                price_whole = product.find('span', {'class': 'a-price-whole'})
                if not price_whole:
                    continue
                    
                price = price_whole.text.strip().replace(',', '')
                price_num = self.clean_price(price)
                
                # Skip if price is 0 or too high
                if price_num == 0 or price_num > 5000:
                    continue
                
                # Extract original price for discount calculation
                original_price_elem = product.find('span', {'class': 'a-price a-text-price'})
                original_price = ""
                discount_percent = 0
                
                if original_price_elem:
                    original_text = original_price_elem.find('span', {'class': 'a-offscreen'})
                    if original_text:
                        original_price = original_text.text.strip()
                        original_num = self.clean_price(original_price)
                        
                        if original_num > price_num:
                            discount_percent = int(((original_num - price_num) / original_num) * 100)
                
                # Only include deals with at least 10% discount or under ₹500
                if discount_percent < 10 and price_num > 500:
                    continue
                
                # Extract image
                img_elem = product.find('img', {'class': 's-image'})
                image_url = img_elem.get('src') if img_elem else ""
                
                # Extract rating
                rating_elem = product.find('span', {'class': 'a-icon-alt'})
                rating = rating_elem.text.strip() if rating_elem else "No rating"
                
                # Extract review count
                reviews_elem = product.find('span', {'class': 'a-size-base s-underline-text'})
                reviews = reviews_elem.text.strip() if reviews_elem else "0"
                
                # Generate affiliate link
                affiliate_link = self.generate_amazon_link(asin)
                
                # Test link accessibility
                link_works = await self.test_link(affiliate_link)
                if not link_works:
                    logger.warning(f"Link not accessible: {asin}")
                    continue
                
                deal = {
                    'asin': asin,
                    'title': title,
                    'price': f"₹{price}",
                    'price_num': price_num,
                    'original_price': original_price,
                    'discount_percent': discount_percent,
                    'image_url': image_url,
                    'rating': rating,
                    'reviews': reviews,
                    'affiliate_link': affiliate_link,
                    'category': category,
                    'hash': product_hash,
                    'timestamp': datetime.now().isoformat()
                }
                
                deals.append(deal)
                
            except Exception as e:
                logger.error(f"Error parsing product: {e}")
                continue
        
        return deals
    
    async def test_link(self, url):
        """Test if Amazon link is accessible"""
        try:
            async with self.session.head(url, allow_redirects=True, timeout=5) as response:
                return response.status in [200, 301, 302]
        except:
            return False
    
    async def get_product_details(self, asin):
        """Get additional product details"""
        url = f"https://www.amazon.in/dp/{asin}"
        
        try:
            async with self.session.get(url, timeout=8) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Try multiple selectors for description
                    description = ""
                    selectors = [
                        {'id': 'productDescription'},
                        {'id': 'feature-bullets'},
                        {'class': 'aplus'},
                        {'id': 'aplus'}
                    ]
                    
                    for selector in selectors:
                        elem = soup.find('div', selector)
                        if elem:
                            description = elem.get_text(strip=True, separator='\n')[:400]
                            break
                    
                    if not description:
                        # Try to get from bullet points
                        feature_bullets = soup.find('div', {'id': 'feature-bullets'})
                        if feature_bullets:
                            points = []
                            for li in feature_bullets.find_all('li')[:3]:
                                points.append(li.get_text(strip=True))
                            description = " • ".join(points)
                    
                    return {'description': description or "Great deal on Amazon!"}
                    
        except Exception as e:
            logger.error(f"Error getting details for {asin}: {e}")
        
        return {'description': "Check out this amazing deal on Amazon!"}
    
    def format_message(self, deal):
        """Format deal for Telegram"""
        # Select emoji based on category
        emoji_map = {
            'electronics': '📱',
            'mobiles': '📱',
            'laptops': '💻',
            'headphones': '🎧',
            'speakers': '🔊',
            'watches': '⌚',
            'cameras': '📷',
            'home-kitchen': '🏠',
            'furniture': '🛋️',
            'decor': '🖼️',
            'clothing': '👕',
            'shoes': '👟',
            'bags': '👜',
            'beauty': '💄',
            'health': '💊',
            'books': '📚',
            'toys': '🧸',
            'sports': '⚽',
            'fitness': '💪',
            'automotive': '🚗',
            'tools': '🛠️',
            'garden': '🌱',
            'pet-supplies': '🐾',
            'grocery': '🛒',
            'stationery': '📝'
        }
        
        emoji = emoji_map.get(deal['category'], '🔥')
        
        # Build message
        message = f"{emoji} *{deal['title']}* {emoji}\n\n"
        
        # Price section
        message += f"💰 *Price:* `{deal['price']}`\n"
        
        if deal['original_price']:
            message += f"📉 *Original:* ~~{deal['original_price']}~~\n"
        
        if deal['discount_percent'] > 0:
            message += f"🎯 *Discount:* _{deal['discount_percent']}% OFF_\n"
        
        # Rating section
        message += f"⭐ *Rating:* {deal['rating']}\n"
        message += f"📊 *Reviews:* {deal['reviews']}\n\n"
        
        # Description
        if deal.get('description'):
            message += f"📝 *Description:*\n{deal['description']}\n\n"
        
        # Link with clear CTA
        message += f"🛍️ *Buy Now:* [Click Here]({deal['affiliate_link']})\n"
        message += f"🔗 *Direct Link:* `{deal['affiliate_link']}`\n\n"
        
        # Footer
        message += f"⏰ {datetime.now().strftime('%d %b %Y • %I:%M %p')}\n"
        message += f"🏷️ #{deal['category'].replace('-', '').title()} #AmazonDeal #SmartDeal"
        
        return message
    
    async def download_image(self, url):
        """Download product image"""
        try:
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.read()
        except Exception as e:
            logger.error(f"Error downloading image: {e}")
        
        # Return default image if download fails
        default_image = "https://via.placeholder.com/400x300/FF9900/FFFFFF?text=Amazon+Deal"
        try:
            async with self.session.get(default_image) as response:
                if response.status == 200:
                    return await response.read()
        except:
            return None
    
    async def post_to_telegram(self, deal):
        """Post deal to Telegram channel"""
        try:
            # Prepare message
            message = self.format_message(deal)
            
            # Download image
            image_data = await self.download_image(deal['image_url'])
            
            # Post to channel
            if image_data:
                await self.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=image_data,
                    caption=message,
                    parse_mode='Markdown'
                )
            else:
                await self.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=message,
                    parse_mode='Markdown'
                )
            
            # Mark as posted
            self.posted_products.add(deal['hash'])
            self.deal_tracker[deal['asin']] = {
                'title': deal['title'],
                'price': deal['price'],
                'posted_at': datetime.now().isoformat()
            }
            
            logger.info(f"✅ Posted: {deal['title'][:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to post: {e}")
            return False
    
    async def find_best_deals(self, max_deals=5):
        """Find best deals across all categories"""
        all_deals = []
        
        logger.info("🔍 Searching for best deals...")
        
        # Search in random categories
        random_categories = random.sample(self.categories, min(8, len(self.categories)))
        
        for category in random_categories:
            try:
                # Random price range for variety
                min_price, max_price = random.choice(self.price_ranges)
                
                logger.info(f"  Searching {category} (₹{min_price}-₹{max_price})...")
                
                deals = await self.search_amazon_deals(
                    category=category,
                    min_price=min_price,
                    max_price=max_price,
                    pages=1  # Only first page for speed
                )
                
                if deals:
                    all_deals.extend(deals)
                    logger.info(f"    Found {len(deals)} deals")
                
                # Delay between category searches
                await asyncio.sleep(random.uniform(3, 6))
                
            except Exception as e:
                logger.error(f"Error in category {category}: {e}")
                continue
        
        # Remove duplicates by ASIN
        unique_deals = {}
        for deal in all_deals:
            if deal['asin'] not in unique_deals:
                unique_deals[deal['asin']] = deal
        
        all_deals = list(unique_deals.values())
        
        # Sort by discount percentage (highest first), then by price (lowest first)
        all_deals.sort(key=lambda x: (-x['discount_percent'], x['price_num']))
        
        # Get additional details for top deals
        final_deals = []
        for deal in all_deals[:max_deals + 5]:  # Get extra for buffer
            details = await self.get_product_details(deal['asin'])
            deal.update(details)
            final_deals.append(deal)
            await asyncio.sleep(1)  # Rate limiting
        
        return final_deals[:max_deals]
    
    async def run(self):
        """Main bot execution"""
        await self.create_session()
        
        logger.info("🚀 Smart Deals Bot Started!")
        logger.info(f"📢 Channel: {CHANNEL_ID}")
        logger.info(f"🏷️ Affiliate: {AFFILIATE_TAG}")
        logger.info(f"📊 Posted before: {len(self.posted_products)} products")
        
        try:
            # Find best deals
            deals = await self.find_best_deals(max_deals=5)
            
            if not deals:
                logger.warning("No new deals found!")
                return 0
            
            # Post deals
            posted_count = 0
            for deal in deals:
                # Double-check not posted
                if deal['hash'] in self.posted_products:
                    continue
                
                success = await self.post_to_telegram(deal)
                if success:
                    posted_count += 1
                    # Delay between posts
                    delay = random.uniform(15, 25)
                    await asyncio.sleep(delay)
            
            # Save tracker
            self.save_tracker()
            
            logger.info(f"🎯 Total posted: {posted_count} deals")
            return posted_count
            
        except Exception as e:
            logger.error(f"❌ Bot error: {e}")
            return 0
        finally:
            await self.close_session()

async def main():
    """Main function"""
    bot = SmartDealsBot()
    return await bot.run()

if __name__ == "__main__":
    # For GitHub Actions (run once)
    result = asyncio.run(main())
    
    # Exit with code based on result
    exit(0 if result > 0 else 1)