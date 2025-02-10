import json
import csv
import os
from datetime import datetime, timedelta
from atproto_client.models import get_or_create
from atproto import CAR, models
from atproto_firehose import FirehoseSubscribeReposClient, parse_subscribe_repos_message
from collections import defaultdict, deque
import time
from pathlib import Path
from rich.live import Live
from rich.table import Table
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.syntax import Syntax
from rich import box
import threading
from queue import Queue
import re
import psutil
import humanize
from typing import Optional, Dict, List, Set
from rich.console import Group
from rich.text import Text

class JSONExtra(json.JSONEncoder):
    def default(self, obj):
        try:
            return json.JSONEncoder.default(self, obj)
        except:
            return repr(obj)

class EnhancedStats:
    def __init__(self):
        self.total_posts = 0
        self.total_users = 0
        self.posts_with_images = 0
        self.posts_with_links = 0
        self.replies = 0
        self.start_time = time.time()
        
        self.posts_per_minute = deque(maxlen=60)  # Last 60 minutes
        self.posts_per_hour = deque(maxlen=24)    # Last 24 hours
        self.posts_this_minute = 0
        self.minute_start_time = time.time()
        
        self.language_stats = defaultdict(int)
        self.most_active_users = defaultdict(int)
        self.popular_domains = defaultdict(int)
        self.media_types = defaultdict(int)
        self.hashtag_stats = defaultdict(int)
        
        self.processing_times = deque(maxlen=1000)
        self.memory_usage = deque(maxlen=60)
        self.cpu_usage = deque(maxlen=60)
        
        self.recent_posts = deque(maxlen=5)
        self.active_users_last_hour: Set[str] = set()
        self.last_minute_timestamp = time.time()
        self.last_hour_timestamp = time.time()

    def update_time_based_metrics(self):
        current_time = time.time()
        
        # Update minute stats
        if current_time - self.last_minute_timestamp >= 60:
            self.posts_per_minute.append(self.posts_this_minute)
            self.posts_this_minute = 0
            self.last_minute_timestamp = current_time
            
        # Update hourly stats
        if current_time - self.last_hour_timestamp >= 3600:
            total_posts_hour = sum(self.posts_per_minute)
            self.posts_per_hour.append(total_posts_hour)
            self.last_hour_timestamp = current_time
            self.active_users_last_hour.clear()

    def get_processing_stats(self) -> Dict[str, float]:
        if not self.processing_times:
            return {"avg": 0, "min": 0, "max": 0}
        return {
            "avg": sum(self.processing_times) / len(self.processing_times),
            "min": min(self.processing_times),
            "max": max(self.processing_times)
        }

class FirehoseMonitor:
    def __init__(self, data_dir: str = "bluesky_data"):
            self.client = FirehoseSubscribeReposClient()
            self.data_dir = Path(data_dir)
            self.data_dir.mkdir(exist_ok=True)
            
            # Create users directory
            self.users_dir = self.data_dir / "users"
            self.users_dir.mkdir(exist_ok=True)
            
            # Create analytics directory
            self.analytics_dir = self.data_dir / "analytics"
            self.analytics_dir.mkdir(exist_ok=True)
            
            # Enhanced statistics
            self.stats = EnhancedStats()
            
            # Initialize user count from existing directories
            self.init_user_count()
            
            # Create queues for thread-safe operations
            self.file_queue = Queue()
            self.display_queue = Queue()
            
            # Start worker threads
            self.writer_thread = threading.Thread(target=self.file_writer, daemon=True)
            self.writer_thread.start()
            
            # Initialize rich components
            self.init_rich_components()
            
            # Performance monitoring
            self.process = psutil.Process()

    def init_user_count(self):
        """Initialize user count from existing directories"""
        try:
            # Count directories that have actual data files
            total_users = 0
            for user_dir in self.users_dir.iterdir():
                if user_dir.is_dir():
                    # Check if directory has any CSV files
                    has_data = any(f.suffix == '.csv' for f in user_dir.iterdir())
                    if has_data:
                        total_users += 1
                        # Create counted marker
                        (user_dir / '.counted').touch()
            
            self.stats.total_users = total_users
            
        except Exception as e:
            print(f"Error initializing user count: {e}")
            self.stats.total_users = 0  # Reset to 0 on error

    def init_rich_components(self):
        """Initialize rich UI components"""
        self.layout = Layout()
        
        # Create main layout
        self.layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3)
        )
        
        # Split main area into sections
        self.layout["main"].split_row(
            Layout(name="stats", ratio=2),
            Layout(name="activity", ratio=3)
        )
        
        # Split stats into upper and lower
        self.layout["stats"].split_column(
            Layout(name="metrics", ratio=2),
            Layout(name="performance", ratio=1)
        )
        
        # Split activity into sections
        self.layout["activity"].split_column(
            Layout(name="recent_posts", ratio=2),
            Layout(name="analytics", ratio=1)
        )

    def clean_text(self, text: Optional[str]) -> str:
        """Clean text for CSV storage"""
        if text is None:
            return ""
        # Remove newlines and normalize whitespace
        text = re.sub(r'\s+', ' ', str(text).strip())
        # Escape any remaining special characters
        return text.replace('"', '""')

    def get_user_dir(self, author_did: str) -> Path:
        """Get or create directory for specific user"""
        # Sanitize DID for filesystem
        safe_did = re.sub(r'[<>:"/\\|?*]', '_', author_did)
        user_dir = self.users_dir / safe_did
        user_dir.mkdir(exist_ok=True)
        return user_dir

    def get_user_files(self, author_did: str) -> Dict[str, Path]:
        """Get paths for user's data files"""
        user_dir = self.get_user_dir(author_did)
        return {
            'posts': user_dir / 'posts.csv',
            'links': user_dir / 'links.csv',
            'media': user_dir / 'media.csv',
            'interactions': user_dir / 'interactions.csv',
            'metadata': user_dir / 'metadata.json'
        }

    def file_writer(self):
        """Thread function to handle file writing"""
        while True:
            data = self.file_queue.get()
            if data is None:  # Poison pill
                break
                
            file_path, row, headers = data
            file_exists = file_path.exists()
            
            try:
                mode = 'a' if file_exists else 'w'
                with open(file_path, mode, newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    if not file_exists:
                        writer.writerow(headers)
                    writer.writerow(row)
            except Exception as e:
                print(f"Error writing to file {file_path}: {e}")

    def extract_hashtags(self, text: str) -> List[str]:
        """Extract hashtags from text"""
        return re.findall(r'#(\w+)', text)

    def extract_domains(self, url: str) -> str:
        """Extract domain from URL"""
        try:
            return url.split('/')[2]
        except (IndexError, AttributeError):
            return "unknown"

    def generate_header(self) -> Panel:
        """Generate header panel"""
        runtime = time.time() - self.stats.start_time
        runtime_str = str(timedelta(seconds=int(runtime)))
        
        header_text = (
            f"[bold blue]Bluesky Firehose Monitor[/bold blue] | "
            f"Runtime: {runtime_str} | "
            f"Active Users: {len(self.stats.active_users_last_hour):,} | "
            f"Posts/min: {self.stats.posts_this_minute:,}"
        )
        return Panel(header_text, style="white on blue")

    def generate_metrics_panel(self) -> Panel:
        """Generate main metrics panel"""
        table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
        
        # Add columns
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Last Minute", style="green", justify="right")
        table.add_column("Last Hour", style="yellow", justify="right")
        table.add_column("Total", style="red", justify="right")
        
        # Calculate rates
        posts_last_min = self.stats.posts_this_minute
        posts_last_hour = sum(self.stats.posts_per_minute) if self.stats.posts_per_minute else 0
        
        # Add rows
        table.add_row(
            "Posts",
            f"{posts_last_min:,}",
            f"{posts_last_hour:,}",
            f"{self.stats.total_posts:,}"
        )
        table.add_row(
            "Users",
            f"{len(self.stats.active_users_last_hour):,}",
            "-",
            f"{self.stats.total_users:,}"
        )
        table.add_row(
            "Media Posts",
            f"{self.stats.posts_with_images:,}",
            "-",
            f"{(self.stats.posts_with_images/max(1, self.stats.total_posts))*100:.1f}%"
        )
        table.add_row(
            "Posts with Links",
            f"{self.stats.posts_with_links:,}",
            "-",
            f"{(self.stats.posts_with_links/max(1, self.stats.total_posts))*100:.1f}%"
        )
        
        return Panel(table, title="[bold]Metrics Overview[/bold]", border_style="blue")

    def create_progress_bar(self, description: str, completed: float) -> str:
            """Create a static progress bar"""
            width = 50
            filled = int(width * min(1, completed / 100))
            bar = "━" * filled + "╸" + "━" * (width - filled - 1)
            percentage = min(100, completed)
            return f"{description:<30} {bar} {percentage:>3.0f}%"

    def generate_performance_panel(self) -> Panel:
        """Generate performance metrics panel without using Progress"""
        from rich.console import Group
        from rich.text import Text
        
        # Get system metrics
        memory_usage = self.process.memory_info().rss / 1024 / 1024  # MB
        cpu_percent = self.process.cpu_percent()
        queue_size = self.file_queue.qsize()
        
        # Get processing stats
        proc_stats = self.stats.get_processing_stats()
        
        # Create progress bars as text
        memory_bar = self.create_progress_bar(
            f"Memory Usage: {memory_usage:.1f}MB",
            min(100, memory_usage/100)
        )
        cpu_bar = self.create_progress_bar(
            f"CPU Usage: {cpu_percent:.1f}%",
            cpu_percent
        )
        queue_bar = self.create_progress_bar(
            f"Queue Size: {queue_size}",
            min(100, queue_size)
        )
        
        # Create stats text
        stats_text = (
            f"\nProcessing Time (ms): "
            f"Avg: {proc_stats['avg']*1000:.2f}, "
            f"Min: {proc_stats['min']*1000:.2f}, "
            f"Max: {proc_stats['max']*1000:.2f}"
        )
        
        # Combine all content
        content = Text()
        content.append(memory_bar + "\n", style="green")
        content.append(cpu_bar + "\n", style="yellow")
        content.append(queue_bar + "\n", style="blue")
        content.append(stats_text, style="cyan")
        
        return Panel(
            content,
            title="[bold]System Performance[/bold]", 
            border_style="yellow"
        )

    def generate_recent_posts_panel(self) -> Panel:
        """Generate recent posts panel"""
        if not self.stats.recent_posts:
            return Panel("No recent posts", title="[bold]Recent Activity[/bold]", border_style="green")
        
        posts_table = Table(show_header=False, box=box.SIMPLE)
        posts_table.add_column("Time", style="cyan", width=8)
        posts_table.add_column("Author", style="magenta", width=15)
        posts_table.add_column("Content", style="white", width=50)
        
        for timestamp, author, text in self.stats.recent_posts:
            time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
            posts_table.add_row(
                time_str, 
                author[:15], 
                text[:50] + "..." if len(text) > 50 else text
            )
        
        return Panel(posts_table, title="[bold]Recent Activity[/bold]", border_style="green")

    def generate_analytics_panel(self) -> Panel:
        """Generate analytics panel"""
        analytics_table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
        analytics_table.add_column("Category", style="cyan")
        analytics_table.add_column("Top Items", style="white")
        
        # Add popular domains
        top_domains = sorted(
            self.stats.popular_domains.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:3]
        domains_str = ", ".join(f"{domain}: {count}" for domain, count in top_domains)
        analytics_table.add_row("Popular Domains", domains_str)
        
        # Add top media types
        top_media = sorted(
            self.stats.media_types.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:3]
        media_str = ", ".join(f"{media}: {count}" for media, count in top_media)
        analytics_table.add_row("Media Types", media_str)
        
        # Add top hashtags
        top_hashtags = sorted(
            self.stats.hashtag_stats.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:3]
        hashtags_str = ", ".join(f"#{tag}: {count}" for tag, count in top_hashtags)
        analytics_table.add_row("Trending Hashtags", hashtags_str)
        
        return Panel(analytics_table, title="[bold]Analytics[/bold]", border_style="red")

    def update_display(self) -> Layout:
        """Update the live display"""
        # Update layout components
        self.layout["header"].update(self.generate_header())
        self.layout["metrics"].update(self.generate_metrics_panel())
        self.layout["performance"].update(self.generate_performance_panel())
        self.layout["recent_posts"].update(self.generate_recent_posts_panel())
        self.layout["analytics"].update(self.generate_analytics_panel())
        
        return self.layout

    def write_to_user_files(self, raw_data: dict, author_did: str, created_at: str, text: str):
        """Write post data to appropriate user files"""
        user_files = self.get_user_files(author_did)
        
        # Write to posts.csv
        post_headers = [
            'timestamp', 'text', 'has_images', 'has_links',
            'is_reply', 'reply_to_uri', 'thread_root_uri',
            'image_count', 'link_count', 'hashtag_count'
        ]
        
        has_images = 'embed' in raw_data and raw_data['embed'].get('$type') == 'app.bsky.embed.images'
        image_count = len(raw_data.get('embed', {}).get('images', [])) if has_images else 0
        
        has_links = bool(raw_data.get('facets', []))
        link_count = sum(1 for facet in raw_data.get('facets', [])
                        for feature in facet.get('features', [])
                        if feature.get('$type') == 'app.bsky.richtext.facet#link')
        
        hashtags = self.extract_hashtags(text)
        
        post_row = [
            created_at,
            self.clean_text(text),
            '1' if has_images else '0',
            '1' if has_links else '0',
            '1' if 'reply' in raw_data else '0',
            raw_data.get('reply', {}).get('parent', {}).get('uri', ''),
            raw_data.get('reply', {}).get('root', {}).get('uri', ''),
            str(image_count),
            str(link_count),
            str(len(hashtags))
        ]
        
        self.file_queue.put((user_files['posts'], post_row, post_headers))
        
        # Write to links.csv if there are links
        if has_links:
            link_headers = ['timestamp', 'url', 'domain', 'context_text']
            for facet in raw_data['facets']:
                for feature in facet.get('features', []):
                    if feature.get('$type') == 'app.bsky.richtext.facet#link':
                        url = feature.get('uri', '')
                        domain = self.extract_domains(url)
                        link_row = [created_at, url, domain, self.clean_text(text)]
                        self.file_queue.put((user_files['links'], link_row, link_headers))
        
        # Write to media.csv if there are images
        if has_images:
            media_headers = ['timestamp', 'image_alt', 'image_type', 'context_text']
            for img in raw_data['embed'].get('images', []):
                media_row = [
                    created_at,
                    self.clean_text(img.get('alt', '')),
                    img.get('mime', ''),
                    self.clean_text(text)
                ]
                self.file_queue.put((user_files['media'], media_row, media_headers))

    def process_post(self, raw_data: dict, author_did: str):
            """Process a single post with enhanced metrics tracking"""
            start_time = time.time()
            
            # Extract text and metadata
            text = raw_data.get('text', '')
            created_at = raw_data.get('createdAt', '')
            
            try:
                # Check if this is a new user before updating any stats
                user_files = self.get_user_files(author_did)
                user_dir = self.get_user_dir(author_did)
                
                # Only count as new user if the directory was just created
                # Use a special marker file to track if we've counted this user
                user_counted_file = user_dir / '.counted'
                if not user_counted_file.exists():
                    self.stats.total_users += 1
                    # Create marker file
                    user_counted_file.touch()
                
                # Update basic stats
                self.stats.total_posts += 1
                self.stats.posts_this_minute += 1
                self.stats.active_users_last_hour.add(author_did)
                self.stats.most_active_users[author_did] += 1
                
                # Update recent posts with more post details
                post_info = (
                    time.time(),
                    author_did,
                    self.clean_text(text)
                )
                self.stats.recent_posts.appendleft(post_info)
                
                # Process media with better error handling
                if 'embed' in raw_data:
                    embed = raw_data['embed']
                    if isinstance(embed, dict) and embed.get('$type') == 'app.bsky.embed.images':
                        self.stats.posts_with_images += 1
                        for img in embed.get('images', []):
                            mime_type = img.get('mime', 'unknown')
                            self.stats.media_types[mime_type] += 1
                
                # Process links with improved domain extraction
                if raw_data.get('facets'):
                    for facet in raw_data['facets']:
                        for feature in facet.get('features', []):
                            if feature.get('$type') == 'app.bsky.richtext.facet#link':
                                self.stats.posts_with_links += 1
                                url = feature.get('uri', '')
                                domain = self.extract_domains(url)
                                if domain != "unknown":
                                    self.stats.popular_domains[domain] += 1
                
                # Process hashtags
                hashtags = self.extract_hashtags(text)
                for tag in hashtags:
                    tag = tag.lower()
                    self.stats.hashtag_stats[tag] += 1
                
                # Write to user files
                self.write_to_user_files(raw_data, author_did, created_at, text)
                
                # Update time-based metrics
                self.stats.update_time_based_metrics()
                
                # Update performance metrics
                processing_time = time.time() - start_time
                self.stats.processing_times.append(processing_time)
                
                # Update system metrics (limit frequency to reduce overhead)
                current_time = time.time()
                if not hasattr(self, '_last_system_update') or current_time - self._last_system_update >= 1.0:
                    self.stats.memory_usage.append(self.process.memory_info().rss / 1024 / 1024)
                    self.stats.cpu_usage.append(self.process.cpu_percent())
                    self._last_system_update = current_time
                    
            except Exception as e:
                print(f"Error processing post: {e}")
                # Log the error but continue processing
                pass

    def on_message_handler(self, message):
        """Handle incoming firehose messages"""
        try:
            commit = parse_subscribe_repos_message(message)
            if not isinstance(commit, models.ComAtprotoSyncSubscribeRepos.Commit):
                return
                
            car = CAR.from_bytes(commit.blocks)
            for op in commit.ops:
                if op.action == "create" and op.cid:
                    raw = car.blocks.get(op.cid)
                    if raw:
                        cooked = get_or_create(raw, strict=False)
                        
                        if cooked.py_type == "app.bsky.feed.post":
                            # Extract author DID from the operation path
                            author_did = op.path.split('/')[0]
                            self.process_post(raw, author_did)
                        
        except Exception as e:
            print(f"Error processing message: {e}")

    def start(self):
            """Start monitoring with enhanced display"""
            console = Console()
            console.clear()
            
            print("[bold blue]Starting Bluesky Firehose Monitor...[/bold blue]")
            print(f"Saving data to: {self.data_dir.absolute()}")
            print("[bold red]Press Ctrl+C to stop[/bold red]")
            
            # Start the firehose client in a separate thread
            def run_client():
                try:
                    self.client.start(self.on_message_handler)
                except Exception as e:
                    print(f"Error in firehose client: {e}")
            
            client_thread = threading.Thread(target=run_client, daemon=True)
            client_thread.start()
            
            try:
                with Live(self.update_display(), refresh_per_second=4) as live:
                    while True:
                        try:
                            live.update(self.update_display())
                            time.sleep(0.25)  # Shorter sleep for more responsive updates
                        except Exception as e:
                            print(f"Error updating display: {e}")
                            time.sleep(1)  # Wait a bit longer on error
                            
            except KeyboardInterrupt:
                print("\n[bold yellow]Shutting down...[/bold yellow]")
                self.file_queue.put(None)  # Signal writer thread to stop
                self.writer_thread.join()
                
                # Save final analytics
                analytics_file = self.analytics_dir / f"analytics_{int(time.time())}.json"
                analytics_data = {
                    "runtime": time.time() - self.stats.start_time,
                    "total_posts": self.stats.total_posts,
                    "total_users": self.stats.total_users,
                    "popular_domains": dict(self.stats.popular_domains),
                    "media_types": dict(self.stats.media_types),
                    "hashtag_stats": dict(self.stats.hashtag_stats),
                    "most_active_users": dict(self.stats.most_active_users)
                }
                
                with open(analytics_file, 'w', encoding='utf-8') as f:
                    json.dump(analytics_data, f, indent=2, cls=JSONExtra)
                
                print(f"[bold green]Final analytics saved to: {analytics_file}[/bold green]")
                print("[bold green]Data collection completed[/bold green]")

if __name__ == "__main__":
    monitor = FirehoseMonitor()
    monitor.start()
