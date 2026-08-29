// js/stock-picks.js

// Initialize stock picks functionality
document.addEventListener('DOMContentLoaded', function() {
    initializeFilters();
    initializeSearch();
    initializeCountdown();
    initializeCharts();
    initializeLoadMore();
    initializeStockModals();
});

// Filter functionality
function initializeFilters() {
    const filterButtons = document.querySelectorAll('.filter-btn');
    const sortSelect = document.getElementById('sort-select');
    
    filterButtons.forEach(button => {
        button.addEventListener('click', () => {
            // Update active filter
            filterButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            
            const filterValue = button.dataset.filter;
            filterStocks(filterValue);
            
            // Track filter usage
            trackEvent('stock_filter_used', { filter: filterValue });
        });
    });
    
    if (sortSelect) {
        sortSelect.addEventListener('change', (e) => {
            sortStocks(e.target.value);
            trackEvent('stock_sort_used', { sort: e.target.value });
        });
    }
}

function filterStocks(category) {
    const stockCards = document.querySelectorAll('.stock-card');
    
    stockCards.forEach(card => {
        const cardCategory = card.dataset.category;
        const shouldShow = category === 'all' || cardCategory === category;
        
        if (shouldShow) {
            card.classList.remove('filtered-out');
            card.classList.add('filtered-in');
            card.style.display = 'block';
        } else {
            card.classList.remove('filtered-in');
            card.classList.add('filtered-out');
            setTimeout(() => {
                if (card.classList.contains('filtered-out')) {
                    card.style.display = 'none';
                }
            }, 300);
        }
    });
}

function sortStocks(sortBy) {
    const stocksGrid = document.querySelector('.stocks-grid');
    const stockCards = Array.from(document.querySelectorAll('.stock-card'));
    
    stockCards.sort((a, b) => {
        switch (sortBy) {
            case 'return':
                return parseFloat(b.dataset.return) - parseFloat(a.dataset.return);
            case 'risk':
                const riskOrder = { 'low': 1, 'medium': 2, 'high': 3 };
                return riskOrder[a.dataset.risk] - riskOrder[b.dataset.risk];
            case 'date':
            default:
                return new Date(b.dataset.date) - new Date(a.dataset.date);
        }
    });
    
    // Re-append sorted cards
    stockCards.forEach(card => stocksGrid.appendChild(card));
    
    // Add animation
    stockCards.forEach((card, index) => {
        card.style.animationDelay = `${index * 0.1}s`;
        card.classList.add('slide-up');
    });
}

// Search functionality
function initializeSearch() {
    const searchInput = document.getElementById('search-input');
    let searchTimeout;
    
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                searchStocks(e.target.value);
            }, 300);
        });
    }
}

function searchStocks(query) {
    const stockCards = document.querySelectorAll('.stock-card');
    const searchTerm = query.toLowerCase().trim();
    
    stockCards.forEach(card => {
        const symbol = card.querySelector('.stock-symbol').textContent.toLowerCase();
        const name = card.querySelector('.stock-name').textContent.toLowerCase();
        const summary = card.querySelector('.stock-summary').textContent.toLowerCase();
        
        const matches = symbol.includes(searchTerm) || 
                       name.includes(searchTerm) || 
                       summary.includes(searchTerm);
        
        if (matches || searchTerm === '') {
            card.style.display = 'block';
            card.classList.add('fade-in');
        } else {
            card.style.display = 'none';
        }
    });
    
    // Track search
    if (searchTerm) {
        trackEvent('stock_search', { query: searchTerm });
    }
}

// Countdown timer
function initializeCountdown() {
    const countdownTimer = document.getElementById('countdown-timer');
    if (!countdownTimer) return;
    
    // Set target date (next Monday at 9 AM)
    const now = new Date();
    const nextMonday = new Date();
    nextMonday.setDate(now.getDate() + (1 + 7 - now.getDay()) % 7);
    nextMonday.setHours(9, 0, 0, 0);
    
    function updateCountdown() {
        const now = new Date().getTime();
        const distance = nextMonday.getTime() - now;
        
        if (distance < 0) {
            countdownTimer.innerHTML = '<div class="countdown-item"><span class="countdown-number">New</span><span class="countdown-label">Pick Available!</span></div>';
            return;
        }
        
        const days = Math.floor(distance / (1000 * 60 * 60 * 24));
        const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
        const seconds = Math.floor((distance % (1000 * 60)) / 1000);
        
        countdownTimer.innerHTML = `
            <div class="countdown-item">
                <span class="countdown-number">${days}</span>
                <span class="countdown-label">Days</span>
            </div>
            <div class="countdown-item">
                <span class="countdown-number">${hours}</span>
                <span class="countdown-label">Hours</span>
            </div>
            <div class="countdown-item">
                <span class="countdown-number">${minutes}</span>
                <span class="countdown-label">Min</span>
            </div>
            <div class="countdown-item">
                <span class="countdown-number">${seconds}</span>
                <span class="countdown-label">Sec</span>
            </div>
        `;
    }
    
    updateCountdown();
    setInterval(updateCountdown, 1000);
}

// Initialize charts
function initializeCharts() {
    initializeFeaturedStockChart();
    initializePerformanceChart();
}

function initializeFeaturedStockChart() {
    const ctx = document.getElementById('featured-stock-chart');
    if (!ctx) return;
    
    // Sample data for NVIDIA stock
    const data = {
        labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
        datasets: [{
            label: 'NVDA Price',
            data: [240, 265, 280, 320, 380, 420, 480, 520, 580, 650, 720, 875],
            borderColor: '#D2691E',
            backgroundColor: 'rgba(210, 105, 30, 0.1)',
            borderWidth: 3,
            fill: true,
            tension: 0.4
        }, {
            label: 'Target Price',
            data: [1200, 1200, 1200, 1200, 1200, 1200, 1200, 1200, 1200, 1200, 1200, 1200],
            borderColor: '#28a745',
            borderDash: [5, 5],
            borderWidth: 2,
            fill: false
        }]
    };
    
    new Chart(ctx, {
        type: 'line',
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                },
                title: {
                    display: true,
                    text: 'NVIDIA Stock Performance & Target'
                }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    ticks: {
                        callback: function(value) {
                            return '$' + value;
                        }
                    }
                }
            }
        }
    });
}

function initializePerformanceChart() {
    const ctx = document.getElementById('performance-tracking-chart');
    if (!ctx) return;
    
    const data = {
        labels: ['2020', '2021', '2022', '2023', '2024'],
        datasets: [{
            label: 'InvestPro Elite Returns',
            data: [45, 78, -12, 89, 127],
            backgroundColor: 'rgba(210, 105, 30, 0.8)',
            borderColor: '#D2691E',
            borderWidth: 2
        }, {
            label: 'S&P 500 Returns',
            data: [16, 27, -19, 24, 18],
            backgroundColor: 'rgba(108, 117, 125, 0.8)',
            borderColor: '#6c757d',
            borderWidth: 2
        }]
    };
    
    new Chart(ctx, {
        type: 'bar',
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                },
                title: {
                    display: true,
                    text: 'Annual Performance Comparison'
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return value + '%';
                        }
                    }
                }
            }
        }
    });
}

// Load more functionality
function initializeLoadMore() {
    const loadMoreBtn = document.getElementById('load-more-btn');
    if (!loadMoreBtn) return;
    
    loadMoreBtn.addEventListener('click', () => {
        loadMoreStocks();
        trackEvent('load_more_stocks');
    });
}

function loadMoreStocks() {
    const loadMoreBtn = document.getElementById('load-more-btn');
    const stocksGrid = document.querySelector('.stocks-grid');
    
    // Show loading state
    loadMoreBtn.classList.add('loading');
    loadMoreBtn.textContent = 'Loading...';
    
    // Simulate API call
    setTimeout(() => {
        const additionalStocks = generateAdditionalStocks();
        additionalStocks.forEach(stock => {
            stocksGrid.appendChild(stock);
        });
        
        // Reset button
        loadMoreBtn.classList.remove('loading');
        loadMoreBtn.textContent = 'Load More Picks';
        
        // Initialize AOS for new elements
        if (typeof AOS !== 'undefined') {
            AOS.refresh();
        }
    }, 1500);
}

function generateAdditionalStocks() {
    const stockData = [
        {
            symbol: 'AAPL',
            name: 'Apple Inc',
            price: '$189.95',
            change: '+1.2%',
            target: '$220',
            return: '+24.8%',
            category: 'tech',
            tags: ['Tech', 'Growth'],
            summary: 'iPhone 15 cycle and services growth driving revenue.',
            date: '2023-12-28'
        },
        {
            symbol: 'META',
            name: 'Meta Platforms',
            price: '$352.89',
            change: '+3.1%',
            target: '$420',
            return: '+38.2%',
            category: 'tech',
            tags: ['Tech', 'AI'],
            summary: 'Metaverse investments paying off with VR adoption.',
            date: '2023-12-25'
        }
    ];
    
    return stockData.map(stock => createStockCard(stock));
}

function createStockCard(stock) {
    const card = document.createElement('div');
    card.className = 'stock-card fade-in';
    card.dataset.category = stock.category;
    card.dataset.return = parseFloat(stock.return);
    card.dataset.date = stock.date;
    
    card.innerHTML = `
        <div class="stock-card-header">
            <div class="stock-basic-info">
                <div class="stock-symbol">${stock.symbol}</div>
                <div class="stock-name">${stock.name}</div>
            </div>
            <div class="stock-return positive">${stock.return}</div>
        </div>
        
        <div class="stock-card-body">
            <div class="stock-price">${stock.price} <span class="price-change positive">${stock.change}</span></div>
            <div class="stock-target">Target: ${stock.target}</div>
            
            <div class="stock-tags">
                ${stock.tags.map(tag => `<span class="tag tag-${tag.toLowerCase()}">${tag}</span>`).join('')}
            </div>
            
            <p class="stock-summary">${stock.summary}</p>
        </div>
        
        <div class="stock-card-footer">
            <div class="pick-date">${formatDate(stock.date)}</div>
            <button class="btn btn-sm btn-outline">View Details</button>
        </div>
    `;
    
    return card;
}

// Stock detail modals
function initializeStockModals() {
    const stockCards = document.querySelectorAll('.stock-card');
    const modal = createStockModal();
    
    stockCards.forEach(card => {
        const viewButton = card.querySelector('.btn-outline');
        if (viewButton) {
            viewButton.addEventListener('click', (e) => {
                e.stopPropagation();
                const stockData = extractStockData(card);
                showStockModal(stockData);
                trackEvent('stock_detail_viewed', { symbol: stockData.symbol });
            });
        }
    });
}

function createStockModal() {
    const modal = document.createElement('div');
    modal.id = 'stock-modal';
    modal.className = 'stock-modal';
    
    modal.innerHTML = `
        <div class="stock-modal-content">
            <div class="modal-header">
                <h2 id="modal-stock-title">Stock Details</h2>
                <span class="modal-close">×</span>
            </div>
            <div class="modal-body" id="modal-stock-content">
                <!-- Content will be populated dynamically -->
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Close modal functionality
    const closeBtn = modal.querySelector('.modal-close');
    closeBtn.addEventListener('click', () => {
        modal.style.display = 'none';
    });
    
    window.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.style.display = 'none';
        }
    });
    
    return modal;
}

function extractStockData(card) {
    return {
        symbol: card.querySelector('.stock-symbol').textContent,
        name: card.querySelector('.stock-name').textContent,
        price: card.querySelector('.stock-price').textContent,
        target: card.querySelector('.stock-target').textContent,
        return: card.querySelector('.stock-return').textContent,
        summary: card.querySelector('.stock-summary').textContent,
        date: card.querySelector('.pick-date').textContent
    };
}

function showStockModal(stockData) {
    const modal = document.getElementById('stock-modal');
    const title = document.getElementById('modal-stock-title');
    const content = document.getElementById('modal-stock-content');
    
    title.textContent = `${stockData.symbol} - ${stockData.name}`;
    
    content.innerHTML = `
        <div class="modal-stock-header">
            <div class="modal-stock-price">
                <span class="current-price">${stockData.price}</span>
                <span class="target-price">${stockData.target}</span>
                <span class="expected-return">${stockData.return}</span>
            </div>
        </div>
        
        <div class="modal-stock-analysis">
            <h3>Investment Analysis</h3>
            <p>${stockData.summary}</p>
            
            <div class="analysis-sections">
                <div class="analysis-section">
                    <h4>Strengths</h4>
                    <ul>
                        <li>Strong market position</li>
                        <li>Growing revenue streams</li>
                        <li>Solid financial metrics</li>
                    </ul>
                </div>
                
                <div class="analysis-section">
                    <h4>Risks</h4>
                    <ul>
                        <li>Market volatility</li>
                        <li>Competitive pressure</li>
                        <li>Regulatory concerns</li>
                    </ul>
                </div>
            </div>
        </div>
        
        <div class="modal-cta">
            <p>Want full analysis and price alerts?</p>
            <a href="pricing.html" class="btn btn-primary">Upgrade to Premium</a>
        </div>
    `;
    
    modal.style.display = 'block';
}

// Utility functions
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric', 
        year: 'numeric' 
    });
}

// Real-time price updates (simulated)
function initializePriceUpdates() {
    const priceElements = document.querySelectorAll('.stock-price');
    
    setInterval(() => {
        priceElements.forEach(element => {
            // Simulate small price changes
            const change = (Math.random() - 0.5) * 2; // -1% to +1%
            updatePriceDisplay(element, change);
        });
    }, 30000); // Update every 30 seconds
}

function updatePriceDisplay
