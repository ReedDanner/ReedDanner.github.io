// js/main.js

// Initialize AOS (Animate On Scroll)
AOS.init({
    duration: 800,
    easing: 'ease-in-out',
    once: true,
    offset: 100
});

// Global Variables
let currentTestimonial = 0;
const testimonials = document.querySelectorAll('.testimonial-card');
let testimonialInterval;

// DOM Content Loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeNavigation();
    initializeChart();
    initializeTestimonials();
    initializeModals();
    initializeForms();
    initializeScrollEffects();
    initializeExitIntent();
});

// Navigation Functions
function initializeNavigation() {
    const navbar = document.getElementById('navbar');
    const navToggle = document.getElementById('nav-toggle');
    const navMenu = document.getElementById('nav-menu');
    const navLinks = document.querySelectorAll('.nav-link');

    // Navbar scroll effect
    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    });

    // Mobile menu toggle
    navToggle.addEventListener('click', () => {
        navMenu.classList.toggle('active');
        navToggle.classList.toggle('active');
    });

    // Close mobile menu when clicking on links
    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            navMenu.classList.remove('active');
            navToggle.classList.remove('active');
        });
    });

    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
}

// Chart Initialization
function initializeChart() {
    const ctx = document.getElementById('performanceChart');
    if (!ctx) return;

    // Sample performance data
    const performanceData = {
        labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
        datasets: [{
            label: 'InvestPro Elite Returns',
            data: [8.5, 12.3, 15.7, 22.1, 28.4, 35.2, 42.8, 51.3, 58.9, 67.2, 74.8, 82.5],
            borderColor: '#C96F2D',
            backgroundColor: 'rgba(201, 111, 45, 0.1)',
            borderWidth: 3,
            fill: true,
            tension: 0.4
        }, {
            label: 'S&P 500',
            data: [2.1, 3.8, 5.2, 7.9, 9.1, 11.3, 13.7, 15.2, 17.8, 19.4, 21.1, 23.5],
            borderColor: '#BBA14F',
            backgroundColor: 'rgba(187, 161, 79, 0.1)',
            borderWidth: 2,
            fill: false,
            tension: 0.4
        }]
    };

    new Chart(ctx, {
        type: 'line',
        data: performanceData,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        usePointStyle: true,
                        padding: 20,
                        font: {
                            family: 'Inter',
                            size: 12
                        }
                    }
                },
                title: {
                    display: true,
                    text: '2024 Performance Comparison (%)',
                    font: {
                        family: 'Lora',
                        size: 16,
                        weight: 'bold'
                    },
                    padding: 20
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(0,0,0,0.1)'
                    },
                    ticks: {
                        callback: function(value) {
                            return value + '%';
                        }
                    }
                },
                x: {
                    grid: {
                        color: 'rgba(0,0,0,0.1)'
                    }
                }
            },
            interaction: {
                intersect: false,
                mode: 'index'
            },
            elements: {
                point: {
                    radius: 6,
                    hoverRadius: 8
                }
            }
        }
    });
}

// Testimonials Carousel
function initializeTestimonials() {
    if (testimonials.length === 0) return;

    // Start testimonial rotation
    testimonialInterval = setInterval(nextTestimonial, 5000);

    // Pause on hover
    const carousel = document.getElementById('testimonials-carousel');
    if (carousel) {
        carousel.addEventListener('mouseenter', () => {
            clearInterval(testimonialInterval);
        });

        carousel.addEventListener('mouseleave', () => {
            testimonialInterval = setInterval(nextTestimonial, 5000);
        });
    }
}

function changeTestimonial(direction) {
    testimonials[currentTestimonial].classList.remove('active');
    
    currentTestimonial += direction;
    
    if (currentTestimonial >= testimonials.length) {
        currentTestimonial = 0;
    } else if (currentTestimonial < 0) {
        currentTestimonial = testimonials.length - 1;
    }
    
    testimonials[currentTestimonial].classList.add('active');
}

function nextTestimonial() {
    changeTestimonial(1);
}

// Modal Functions
function initializeModals() {
    const modal = document.getElementById('exit-intent-modal');
    const closeBtn = document.querySelector('.close');

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            modal.style.display = 'none';
        });
    }

    // Close modal when clicking outside
    window.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.style.display = 'none';
        }
    });
}

// Form Handling
function initializeForms() {
    // Lead magnet form
    const leadForm = document.getElementById('lead-form');
    if (leadForm) {
        leadForm.addEventListener('submit', handleLeadForm);
    }

    // Exit intent form
    const exitForm = document.getElementById('exit-intent-form');
    if (exitForm) {
        exitForm.addEventListener('submit', handleExitIntentForm);
    }
}

function handleLeadForm(e) {
    e.preventDefault();
    const email = e.target.querySelector('input[type="email"]').value;
    const button = e.target.querySelector('button');
    
    // Show loading state
    const originalText = button.textContent;
    button.innerHTML = '<span class="loading"></span> Sending...';
    button.disabled = true;

    // Simulate API call
    setTimeout(() => {
        // Show success message
        showNotification('Success! Check your email for your free stock pick.', 'success');
        e.target.reset();
        
        // Reset button
        button.textContent = originalText;
        button.disabled = false;
        
        // Track conversion (you would integrate with your analytics here)
        trackEvent('lead_magnet_signup', { email: email });
    }, 2000);
}

function handleExitIntentForm(e) {
    e.preventDefault();
    const email = e.target.querySelector('input[type="email"]').value;
    const modal = document.getElementById('exit-intent-modal');
    
    // Show success and close modal
    showNotification('Success! Your free stock pick is on the way.', 'success');
    modal.style.display = 'none';
    e.target.reset();
    
    // Track conversion
    trackEvent('exit_intent_signup', { email: email });
}

// Scroll Effects
function initializeScrollEffects() {
    // Parallax effect for hero section
    window.addEventListener('scroll', () => {
        const scrolled = window.pageYOffset;
        const hero = document.querySelector('.hero');
        
        if (hero) {
            const rate = scrolled * -0.5;
            hero.style.transform = `translateY(${rate}px)`;
        }
    });

    // Fade in elements on scroll
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
            }
        });
    }, observerOptions);

    // Observe elements with fade-in classes
    document.querySelectorAll('.fade-in, .slide-in-left, .slide-in-right').forEach(el => {
        observer.observe(el);
    });
}

// Exit Intent Detection
function initializeExitIntent() {
    let hasShownExitIntent = false;
    
    document.addEventListener('mouseleave', (e) => {
        if (e.clientY <= 0 && !hasShownExitIntent) {
            showExitIntentModal();
            hasShownExitIntent = true;
        }
    });
}

function showExitIntentModal() {
    const modal = document.getElementById('exit-intent-modal');
    if (modal) {
        modal.style.display = 'block';
        
        // Track event
        trackEvent('exit_intent_shown');
    }
}

// Continuing from showNotification function
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <div class="notification-content">
            <i class="fas fa-${type === 'success' ? 'check-circle' : 'info-circle'}"></i>
            <span>${message}</span>
            <button class="notification-close">×</button>
        </div>
    `;

    // Add styles
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${type === 'success' ? '#28a745' : '#007bff'};
        color: white;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        z-index: 10001;
        transform: translateX(400px);
        transition: transform 0.3s ease;
        max-width: 350px;
    `;

    // Add to DOM
    document.body.appendChild(notification);

    // Animate in
    setTimeout(() => {
        notification.style.transform = 'translateX(0)';
    }, 100);

    // Close button functionality
    const closeBtn = notification.querySelector('.notification-close');
    closeBtn.addEventListener('click', () => {
        removeNotification(notification);
    });

    // Auto remove after 5 seconds
    setTimeout(() => {
        removeNotification(notification);
    }, 5000);
}

function removeNotification(notification) {
    notification.style.transform = 'translateX(400px)';
    setTimeout(() => {
        if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
        }
    }, 300);
}

function trackEvent(eventName, properties = {}) {
    // Integration point for analytics (Google Analytics, Mixpanel, etc.)
    console.log('Event tracked:', eventName, properties);
    
    // Example Google Analytics 4 integration:
    if (typeof gtag !== 'undefined') {
        gtag('event', eventName, properties);
    }
    
    // Example Facebook Pixel integration:
    if (typeof fbq !== 'undefined') {
        fbq('track', eventName, properties);
    }
}

// Countdown Timer Function (for stock picks page)
function initializeCountdown(targetDate) {
    const countdownElement = document.getElementById('countdown-timer');
    if (!countdownElement) return;

    function updateCountdown() {
        const now = new Date().getTime();
        const distance = targetDate - now;

        if (distance < 0) {
            countdownElement.innerHTML = "New picks available!";
            return;
        }

        const days = Math.floor(distance / (1000 * 60 * 60 * 24));
        const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
        const seconds = Math.floor((distance % (1000 * 60)) / 1000);

        countdownElement.innerHTML = `
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
                <span class="countdown-label">Minutes</span>
            </div>
            <div class="countdown-item">
                <span class="countdown-number">${seconds}</span>
                <span class="countdown-label">Seconds</span>
            </div>
        `;
    }

    updateCountdown();
    setInterval(updateCountdown, 1000);
}

// Dark Mode Toggle
function initializeDarkMode() {
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    if (!darkModeToggle) return;

    // Check for saved theme preference
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
        document.body.classList.toggle('dark-mode', savedTheme === 'dark');
    }

    darkModeToggle.addEventListener('click', () => {
        document.body.classList.toggle('dark-mode');
        const isDark = document.body.classList.contains('dark-mode');
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
    });
}

// Price Toggle (Monthly/Annual)
function initializePriceToggle() {
    const priceToggle = document.getElementById('price-toggle');
    if (!priceToggle) return;

    priceToggle.addEventListener('change', (e) => {
        const isAnnual = e.target.checked;
        const monthlyPrices = document.querySelectorAll('.monthly-price');
        const annualPrices = document.querySelectorAll('.annual-price');

        monthlyPrices.forEach(price => {
            price.style.display = isAnnual ? 'none' : 'block';
        });

        annualPrices.forEach(price => {
            price.style.display = isAnnual ? 'block' : 'none';
        });

        // Track pricing toggle
        trackEvent('pricing_toggle', { billing_cycle: isAnnual ? 'annual' : 'monthly' });
    });
}

// Stock Filtering and Sorting
function initializeStockFilters() {
    const filterButtons = document.querySelectorAll('.filter-btn');
    const sortSelect = document.getElementById('sort-select');
    const stockCards = document.querySelectorAll('.stock-card');

    // Filter functionality
    filterButtons.forEach(button => {
        button.addEventListener('click', () => {
            const filter = button.dataset.filter;
            
            // Update active button
            filterButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');

            // Filter stocks
            stockCards.forEach(card => {
                const cardFilter = card.dataset.category;
                if (filter === 'all' || cardFilter === filter) {
                    card.style.display = 'block';
                    card.classList.add('fade-in');
                } else {
                    card.style.display = 'none';
                }
            });

            // Track filter usage
            trackEvent('stock_filter_used', { filter: filter });
        });
    });

    // Sort functionality
    if (sortSelect) {
        sortSelect.addEventListener('change', (e) => {
            const sortBy = e.target.value;
            const container = document.querySelector('.stocks-grid');
            const cards = Array.from(stockCards);

            cards.sort((a, b) => {
                switch (sortBy) {
                    case 'date':
                        return new Date(b.dataset.date) - new Date(a.dataset.date);
                    case 'return':
                        return parseFloat(b.dataset.return) - parseFloat(a.dataset.return);
                    case 'risk':
                        return a.dataset.risk.localeCompare(b.dataset.risk);
                    default:
                        return 0;
                }
            });

            // Re-append sorted cards
            cards.forEach(card => container.appendChild(card));

            // Track sort usage
            trackEvent('stock_sort_used', { sort_by: sortBy });
        });
    }
}

// Form Validation
function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

function validateForm(form) {
    const inputs = form.querySelectorAll('input[required]');
    let isValid = true;

    inputs.forEach(input => {
        const value = input.value.trim();
        const type = input.type;

        // Remove existing error styling
        input.classList.remove('error');

        // Validate based on input type
        if (!value) {
            showFieldError(input, 'This field is required');
            isValid = false;
        } else if (type === 'email' && !validateEmail(value)) {
            showFieldError(input, 'Please enter a valid email address');
            isValid = false;
        }
    });

    return isValid;
}

function showFieldError(input, message) {
    input.classList.add('error');
    
    // Remove existing error message
    const existingError = input.parentNode.querySelector('.field-error');
    if (existingError) {
        existingError.remove();
    }

    // Add new error message
    const errorElement = document.createElement('div');
    errorElement.className = 'field-error';
    errorElement.textContent = message;
    errorElement.style.cssText = `
        color: #dc3545;
        font-size: 0.8rem;
        margin-top: 5px;
        display: block;
    `;
    
    input.parentNode.appendChild(errorElement);
}

// Loading States
function setLoadingState(button, isLoading = true) {
    if (isLoading) {
        button.dataset.originalText = button.textContent;
        button.innerHTML = '<span class="loading"></span> Loading...';
        button.disabled = true;
    } else {
        button.textContent = button.dataset.originalText;
        button.disabled = false;
    }
}

// Local Storage Utilities
function saveToLocalStorage(key, data) {
    try {
        localStorage.setItem(key, JSON.stringify(data));
    } catch (e) {
        console.error('Failed to save to localStorage:', e);
    }
}

function getFromLocalStorage(key) {
    try {
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : null;
    } catch (e) {
        console.error('Failed to read from localStorage:', e);
        return null;
    }
}

// Performance Monitoring
function measurePageLoad() {
    window.addEventListener('load', () => {
        const loadTime = performance.now();
        trackEvent('page_load_time', { 
            load_time: Math.round(loadTime),
            page: window.location.pathname 
        });
    });
}

// Initialize performance monitoring
measurePageLoad();

// Lazy Loading for Images
function initializeLazyLoading() {
    const images = document.querySelectorAll('img[data-src]');
    
    const imageObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                img.src = img.dataset.src;
                img.classList.remove('lazy');
                observer.unobserve(img);
            }
        });
    });

    images.forEach(img => imageObserver.observe(img));
}

// Search Functionality
function initializeSearch() {
    const searchInput = document.getElementById('search-input');
    if (!searchInput) return;

    let searchTimeout;

    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        const query = e.target.value.toLowerCase().trim();

        searchTimeout = setTimeout(() => {
            performSearch(query);
        }, 300);
    });
}

function performSearch(query) {
    const searchableElements = document.querySelectorAll('[data-searchable]');
    
    searchableElements.forEach(element => {
        const text = element.textContent.toLowerCase();
        const isMatch = text.includes(query) || query === '';
        
        element.style.display = isMatch ? 'block' : 'none';
        
        if (isMatch && query) {
            highlightSearchTerm(element, query);
        } else {
            removeHighlight(element);
        }
    });

    // Track search
    if (query) {
        trackEvent('search_performed', { query: query });
    }
}

function highlightSearchTerm(element, term) {
    const regex = new RegExp(`(${term})`, 'gi');
    const originalText = element.dataset.originalText || element.textContent;
    element.dataset.originalText = originalText;
    
    const highlightedText = originalText.replace(regex, '<mark>$1</mark>');
    element.innerHTML = highlightedText;
}

function removeHighlight(element) {
    if (element.dataset.originalText) {
        element.textContent = element.dataset.originalText;
        delete element.dataset.originalText;
    }
}

// Accessibility Enhancements
function initializeAccessibility() {
    // Skip to main content link
    const skipLink = document.createElement('a');
    skipLink.href = '#main-content';
    skipLink.textContent = 'Skip to main content';
    skipLink.className = 'skip-link';
    skipLink.style.cssText = `
        position: absolute;
        top: -40px;
        left: 6px;
        background: var(--slate-navy);
        color: white;
        padding: 8px;
        text-decoration: none;
        border-radius: 4px;
        z-index: 10000;
        transition: top 0.3s;
    `;
    
    skipLink.addEventListener('focus', () => {
        skipLink.style.top = '6px';
    });
    
    skipLink.addEventListener('blur', () => {
        skipLink.style.top = '-40px';
    });
    
    document.body.insertBefore(skipLink, document.body.firstChild);

    // Keyboard navigation for custom elements
    document.querySelectorAll('.btn, .nav-link').forEach(element => {
        element.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                element.click();
            }
        });
    });
}

// Initialize accessibility features
initializeAccessibility();

// Error Handling
window.addEventListener('error', (e) => {
    console.error('JavaScript error:', e.error);
    trackEvent('javascript_error', {
        message: e.message,
        filename: e.filename,
        lineno: e.lineno
    });
});

// Service Worker Registration (for PWA features)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js')
            .then(registration => {
                console.log('SW registered: ', registration);
            })
            .catch(registrationError => {
                console.log('SW registration failed: ', registrationError);
            });
    });
}

// Export functions for use in other files
window.InvestProElite = {
    showNotification,
    trackEvent,
    validateForm,
    setLoadingState,
    saveToLocalStorage,
    getFromLocalStorage,
    initializeCountdown,
    changeTestimonial
};
