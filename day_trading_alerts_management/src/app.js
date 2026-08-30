// Day Trading Alerts Dashboard
// Real-time alert monitoring

const ALERTS_FILE = '../day_trading_alerts/alerts_state.json';
const REFRESH_INTERVAL = 5000; // 5 seconds

class AlertsDashboard {
    constructor() {
        this.alerts = [];
        this.init();
    }

    init() {
        console.log('📊 Alerts Dashboard initialized');
        this.startPolling();
    }

    startPolling() {
        // Poll for new alerts
        setInterval(() => this.fetchAlerts(), REFRESH_INTERVAL);
    }

    async fetchAlerts() {
        try {
            // TODO: Connect to alerts system
            // This will read from ../day_trading_alerts/alerts_state.json
            // and ../day_trading_alerts/logs/alerts.log
            console.log('🔄 Polling for alerts...');
        } catch (error) {
            console.error('Error fetching alerts:', error);
        }
    }

    addAlert(alert) {
        this.alerts.unshift(alert);
        this.updateUI();
    }

    updateUI() {
        this.updateAlertsContainer();
        this.updateStats();
    }

    updateAlertsContainer() {
        const container = document.getElementById('alerts-container');
        if (this.alerts.length === 0) {
            container.innerHTML = '<p>No alerts yet...</p>';
            return;
        }

        container.innerHTML = this.alerts.map(alert => `
            <div class="alert-item ${this.getConfidenceClass(alert.confidence)}">
                <div class="alert-symbol">
                    ${alert.symbol}
                    <span class="alert-confidence ${this.getConfidenceClass(alert.confidence)}">
                        ${alert.confidence}%
                    </span>
                </div>
                <p>Price: $${alert.price.toFixed(2)}</p>
                <p>${alert.reason}</p>
                <p style="font-size: 0.85rem; color: #999; margin-top: 5px;">
                    ${new Date(alert.timestamp).toLocaleTimeString()}
                </p>
            </div>
        `).join('');
    }

    updateStats() {
        document.getElementById('total-alerts').textContent = this.alerts.length;
        
        const today = this.alerts.filter(a => {
            const alertDate = new Date(a.timestamp).toDateString();
            return alertDate === new Date().toDateString();
        }).length;
        document.getElementById('today-alerts').textContent = today;

        if (this.alerts.length > 0) {
            const avgConf = Math.round(
                this.alerts.reduce((sum, a) => sum + a.confidence, 0) / this.alerts.length
            );
            document.getElementById('avg-confidence').textContent = avgConf + '%';
        }
    }

    getConfidenceClass(confidence) {
        if (confidence >= 75) return 'high';
        if (confidence >= 65) return 'medium';
        return 'low';
    }
}

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new AlertsDashboard();
});
