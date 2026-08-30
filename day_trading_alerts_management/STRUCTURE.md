# Project Structure

## Day Trading Alerts Management Dashboard

```
day_trading_alerts_management/
│
├── .claude-project          # Claude Code project metadata
├── index.html               # Main HTML dashboard
├── README.md                # Project overview
├── STRUCTURE.md             # This file
│
├── src/
│   ├── app.js               # Main dashboard logic
│   ├── integration.js       # Integration with alerts system
│   ├── charts.js            # Chart rendering (future)
│   ├── watchlist.js         # Watchlist management (future)
│   └── config.js            # Configuration settings
│
├── public/
│   ├── style.css            # Dashboard styling
│   ├── responsive.css       # Mobile responsive
│   └── theme.css            # Color themes
│
├── data/
│   ├── alerts.json          # Local alerts cache
│   ├── watchlist.json       # Saved watchlist
│   └── settings.json        # Dashboard settings
│
└── logs/
    └── dashboard.log        # Dashboard logs
```

## Features

### Phase 1 (Current)
- [ ] Dashboard layout (HTML/CSS)
- [ ] Live alerts display
- [ ] Basic statistics

### Phase 2
- [ ] Real-time data sync
- [ ] Watchlist management
- [ ] Alert accuracy tracking
- [ ] Charts & analytics

### Phase 3
- [ ] Settings/configuration UI
- [ ] Alert filtering & search
- [ ] Export alerts history
- [ ] Mobile responsive

## Integration Points

Connects to `../day_trading_alerts/`:
- Reads `alerts_state.json` for alert status
- Tails `logs/alerts.log` for real-time updates
- Monitors `watchlist` configuration

## Technology Stack

- **Frontend**: Vanilla JavaScript (no build tools)
- **Styling**: CSS3 (Flexbox, Grid)
- **Backend**: Static files (no server needed initially)
- **Data**: JSON files

## How It Works

1. Dashboard loads HTML/CSS
2. JavaScript connects to alerts system
3. Polls `alerts_state.json` every 5 seconds
4. Displays new alerts in real-time
5. Calculates statistics and hit rate
