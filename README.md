# 🌌 Bluesky Firehose Monitor

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![AT Protocol](https://img.shields.io/badge/AT%20Protocol-Compatible-blue.svg)](https://atproto.com/)

A powerful, real-time monitoring tool for the Bluesky social network firehose. Track posts, analyze trends, and collect data with an elegant terminal UI.

## ✨ Features

- 🔄 Real-time post monitoring
- 📊 Live statistics and metrics
- 💾 Automated data collection and organization
- 📈 Performance monitoring
- 🎨 Rich terminal UI with live updates
- 🔍 Detailed analytics tracking

## 🖥️ Terminal UI Preview

```
┌─────────────────────────────────────────────────────────────┐
│                 Bluesky Firehose Monitor                    │
└─────────────────────────────────────────────────────────────┘
┌─────────────────┐  ┌─────────────────────────────────────┐
│  Live Metrics   │  │         Recent Activity             │
│  • Posts/min    │  │  • Latest posts                    │
│  • Users        │  │  • Trending topics                 │
│  • Media stats  │  │  • Active discussions              │
└─────────────────┘  └─────────────────────────────────────┘
```

## 📋 Requirements

| Requirement | Version |
|------------|---------|
| Python | ≥ 3.7 |
| atproto | Latest |
| rich | Latest |
| psutil | Latest |

## 🚀 Quick Start

1. Clone the repository:
```bash
git clone https://github.com/pentestfunctions/bluesky-scraper.git
cd bluesky-scraper
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the monitor:
```bash
python monitor.py
```

## 📁 Data Structure

The scraper organizes data in the following structure:

```
bluesky_data/
├── users/
│   ├── user_did/
│   │   ├── posts.csv
│   │   ├── links.csv
│   │   ├── media.csv
│   │   └── metadata.json
├── analytics/
│   └── analytics_{timestamp}.json
```

## 📊 Collected Metrics

| Category | Description |
|----------|-------------|
| Posts | Total posts, posts per minute/hour |
| Users | Active users, total unique users |
| Media | Images, videos, external links |
| Analytics | Hashtags, domains, engagement |
| Performance | CPU usage, memory usage, processing time |

## 🔍 Features in Detail

### Real-time Monitoring
- Post tracking with timestamps
- User activity monitoring
- Media and link detection
- Hashtag tracking

### Data Collection
- Automated CSV generation
- User-specific data organization
- Link and media cataloging
- Analytics aggregation

### Performance Metrics
- Processing time tracking
- System resource monitoring
- Queue management
- Error handling

## 🛠️ Configuration

The monitor can be configured through the following parameters:

```python
monitor = FirehoseMonitor(
    data_dir="bluesky_data"  # Change default data directory
)
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [ATProto](https://atproto.com/)
- UI powered by [Rich](https://github.com/Textualize/rich)
- Inspired by the Bluesky community

## ⚠️ Disclaimer

This tool is for educational and research purposes only. Please respect Bluesky's terms of service and API usage guidelines when using this tool.

---

Made with ❤️ by [pentestfunctions](https://github.com/pentestfunctions)
