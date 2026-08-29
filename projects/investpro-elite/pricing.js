// js/pricing.js

// Initialize pricing page functionality
document.addEventListener('DOMContentLoaded', function() {
    initializePriceToggle();
    initializeFAQ();
    initializePlanSelection();
});

// Price Toggle Functionality
function initializePriceToggle() {
    const priceToggle = document.getElementById('price-toggle');
    if (!priceToggle) return;

    priceToggle.addEventListener('change', (e) => {
        const isAnnual = e.target.checked;
        togglePricing(isAnnual);
        
        // Track pricing toggle
        trackEvent('pricing_toggle', { 
            billing_cycle: isAnnual ? 'annual' : 'monthly' 
        });
    });
}

function togglePricing(isAnnual) {
    const monthlyPrices = document.querySelectorAll('.monthly-price');
    const annualPrices = document.querySelectorAll('.annual-price');

    monthlyPrices.forEach(element => {
        element.style.display = isAnnual ? 'none' : 'inline';
    });

    annualPrices.forEach(element => {
        element.style.display = isAnnual ? 'inline' : 'none';
    });

    // Add animation effect
    document.querySelectorAll('.plan-card').forEach(card => {
        card.style.transform = 'scale(0.95)';
        setTimeout(() => {
            card.style.transform = '';
        }, 200);
    });
}

// FAQ Functionality
function initializeFAQ() {
    const faqItems = document.querySelectorAll('.faq-item');
    
    faqItems.forEach(item => {
        const question = item.querySelector('.faq-question');
        
        question.addEventListener('click', () => {
            const isActive = item.classList.contains('active');
            
            // Close all other FAQ items
            faqItems.forEach(otherItem => {
                if (otherItem !== item) {
                    otherItem.classList.remove('active');
                }
            });
            
            // Toggle current item
            item.classList.toggle('active', !isActive);
            
            // Track FAQ interaction
            trackEvent('faq_clicked', { 
                question: question.querySelector('h3').textContent 
            });
        });
    });
}

// Plan Selection
function initializePlanSelection() {
    const modal = document.getElementById('plan-modal');
    const closeBtn = modal.querySelector('.close');
    const form = document.getElementById('plan-selection-form');

    // Close modal functionality
    closeBtn.addEventListener('click', () => {
        modal.style.display = 'none';
    });

    window.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.style.display = 'none';
        }
    });

    // Form submission
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        handlePlanSelection(e);
    });
}

function selectPlan(planType) {
    const modal = document.getElementById('plan-modal');
    const selectedPlanInput = document.getElementById('selected-plan');
    
    selectedPlanInput.value = planType;
    modal.style.display = 'block';
    
    // Update modal content based on plan
    updateModalContent(planType);
    
    // Track plan selection
    trackEvent('plan_selected', { plan: planType });
}

function updateModalContent(planType) {
    const modal = document.getElementById('plan-modal');
    const title = modal.querySelector('h2');
    const description = modal.querySelector('p');
    
    const planDetails = {
        premium: {
            title: 'Start Your Premium Trial',
            description: 'Get 14 days free, then $49/month. Cancel anytime.'
        },
        pro: {
            title: 'Start Your Pro Trial',
            description: 'Get 14 days free, then $99/month. Cancel anytime.'
        }
    };
    
    if (planDetails[planType]) {
        title.textContent = planDetails[planType].title;
        description.textContent = planDetails[planType].description;
    }
}

function handlePlanSelection(e) {
    const email = e.target.querySelector('input[type="email"]').value;
    const plan = document.getElementById('selected-plan').value;
    const button = e.target.querySelector('button');
    
    // Validate email
    if (!validateEmail(email)) {
        showNotification('Please enter a valid email address', 'error');
        return;
    }
    
    // Show loading state
    setLoadingState(button, true);
    
    // Simulate API call for trial signup
    setTimeout(() => {
        // Hide modal
        document.getElementById('plan-modal').style.display = 'none';
        
        // Show success message
        showNotification('Success! Check your email to complete your trial signup.', 'success');
        
        // Reset form
        e.target.reset();
        setLoadingState(button, false);
        
        // Track conversion
        trackEvent('trial_signup', { 
            plan: plan,
            email: email 
        });
        
        // Redirect to signup page (in real implementation)
        // window.location.href = `signup.html?plan=${plan}&email=${encodeURIComponent(email)}`;
        
    }, 2000);
}

// Plan comparison highlighting
function highlightPlanFeatures() {
    const planCards = document.querySelectorAll('.plan-card');
    
    planCards.forEach(card => {
        card.addEventListener('mouseenter', () => {
            // Dim other cards
            planCards.forEach(otherCard => {
                if (otherCard !== card) {
                    otherCard.style.opacity = '0.7';
                }
            });
        });
        
        card.addEventListener('mouseleave', () => {
            // Restore all cards
            planCards.forEach(otherCard => {
                otherCard.style.opacity = '1';
            });
        });
    });
}

// Initialize plan highlighting
highlightPlanFeatures();

// Pricing calculator (for custom plans)
function calculateCustomPricing(users, features) {
    let basePrice = 29;
    let userPrice = users * 5;
    let featurePrice = features.length * 10;
    
    return basePrice + userPrice + featurePrice;
}

// Currency conversion (if needed for international users)
function convertCurrency(amount, fromCurrency, toCurrency) {
    // This would integrate with a currency API in production
    const exchangeRates = {
        'USD': { 'EUR': 0.85, 'GBP': 0.73, 'CAD': 1.25 },
        'EUR': { 'USD': 1.18, 'GBP': 0.86, 'CAD': 1.47 },
        'GBP': { 'USD': 1.37, 'EUR': 1.16, 'CAD': 1.71 }
    };
    
    if (fromCurrency === toCurrency) return amount;
    
    const rate = exchangeRates[fromCurrency]?.[toCurrency] || 1;
    return Math.round(amount * rate * 100) / 100;
}

// A/B Testing for pricing
function initializePricingABTest() {
    const testVariant = Math.random() < 0.5 ? 'A' : 'B';
    
    if (testVariant === 'B') {
        // Show alternative pricing
        const premiumPrice = document.querySelector('.plan-card:nth-child(2) .monthly-price');
        if (premiumPrice) {
            premiumPrice.textContent = '$39'; // Reduced price for test
        }
    }
    
    // Track which variant user sees
    trackEvent('pricing_ab_test', { variant: testVariant });
}

// Initialize A/B test
// initializePricingABTest();

// Pricing page analytics
function trackPricingPageView() {
    trackEvent('pricing_page_view', {
        timestamp: new Date().toISOString(),
        user_agent: navigator.userAgent,
        referrer: document.referrer
    });
}

// Track page view
trackPricingPageView();

// Exit intent for pricing page
let pricingExitIntentShown = false;

document.addEventListener('mouseleave', (e) => {
    if (e.clientY <= 0 && !pricingExitIntentShown) {
        showPricingExitIntent();
        pricingExitIntentShown = true;
    }
});

function showPricingExitIntent() {
    // Show special discount offer
    showNotification('Wait! Get 20% off your first month with code SAVE20', 'info');
    
    trackEvent('pricing_exit_intent');
}

// Scroll-based pricing highlights
function initializeScrollHighlights() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('highlight-animate');
                
                // Track which plan is viewed
                const planName = entry.target.querySelector('h3')?.textContent;
                if (planName) {
                    trackEvent('plan_viewed', { plan: planName.toLowerCase() });
                }
            }
        });
    }, { threshold: 0.5 });

    document.querySelectorAll('.plan-card').forEach(card => {
        observer.observe(card);
    });
}

// Initialize scroll highlights
initializeScrollHighlights();

// Add CSS for highlight animation
const style = document.createElement('style');
style.textContent = `
    .highlight-animate {
        animation: highlightPulse 2s ease-in-out;
    }
    
    @keyframes highlightPulse {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(1.02); }
    }
`;
document.head.appendChild(style);
