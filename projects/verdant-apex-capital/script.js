// script.js – shared across all Verdant Apex Capital pages
// IMPORTANT:
// - Requires Supabase client loaded as window.supabaseClient (see supabaseClient.js)
// - Research ordering expects research_reports has is_manager_post boolean column
// - Pro upgrade buttons redirect to pricing.html (payment plans page)

document.addEventListener('DOMContentLoaded', async () => {
  // =============================
  // 1) NAV TOGGLE / MOBILE MENU
  // =============================
  const navToggle = document.getElementById('nav-toggle');
  const navMenu = document.getElementById('nav-menu');
  const navbar = document.getElementById('navbar');

  if (navToggle && navMenu) {
    navToggle.addEventListener('click', () => {
      navMenu.classList.toggle('active');
      navToggle.classList.toggle('active');
    });
  }

  // highlight active nav based on path
  const currentPath = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-link').forEach(link => {
    const href = link.getAttribute('href');
    if (!href) return;
    if (href === currentPath || (currentPath === '' && href === 'index.html')) {
      link.classList.add('active');
    }
  });

  // navbar shadow on scroll (only where navbar exists)
  if (navbar) {
    window.addEventListener('scroll', () => {
      if (window.scrollY > 40) navbar.classList.add('scrolled');
      else navbar.classList.remove('scrolled');
    });
  }

  // =============================
  // 2) SUPABASE AUTH + NAV UI
  // =============================
  const sb = window.supabaseClient;

  async function refreshAuthUI() {
    const authLink = document.getElementById('nav-auth-link');
    const logoutLink = document.getElementById('nav-logout-link');
    if (!sb || (!authLink && !logoutLink)) return;

    const { data: { user } } = await sb.auth.getUser();

    if (user) {
      if (authLink) {
        authLink.textContent = 'Account';
        authLink.href = 'research.html';
      }
      if (logoutLink) logoutLink.style.display = 'inline-block';
    } else {
      if (authLink) {
        authLink.textContent = 'Sign in';
        authLink.href = 'auth.html';
      }
      if (logoutLink) logoutLink.style.display = 'none';
    }
  }

  // =============================
// MEMBERSHIPS BILLING TOGGLE (pricing.html)
// =============================
const billingMonthly = document.getElementById('billingMonthly');
const billingAnnual = document.getElementById('billingAnnual');

if (billingMonthly && billingAnnual) {
  const pricePro = document.getElementById('pricePro');
  const periodPro = document.getElementById('periodPro');
  const subpricePro = document.getElementById('subpricePro');

  const priceMentor = document.getElementById('priceMentor');
  const periodMentor = document.getElementById('periodMentor');
  const subpriceMentor = document.getElementById('subpriceMentor');

  function setMonthly() {
    billingMonthly.classList.add('active');
    billingAnnual.classList.remove('active');

    if (pricePro) pricePro.textContent = '$29';
    if (periodPro) periodPro.textContent = '/month';
    if (subpricePro) subpricePro.textContent = '$249/year billed annually';

    if (priceMentor) priceMentor.textContent = '$199';
    if (periodMentor) periodMentor.textContent = '/month';
    if (subpriceMentor) subpriceMentor.textContent = '$1,999/year billed annually';
  }

  function setAnnual() {
    billingAnnual.classList.add('active');
    billingMonthly.classList.remove('active');

    // show the annual effective price (optional)
    if (pricePro) pricePro.textContent = '$249';
    if (periodPro) periodPro.textContent = '/year';
    if (subpricePro) subpricePro.textContent = 'Best value billed yearly';

    if (priceMentor) priceMentor.textContent = '$1,999';
    if (periodMentor) periodMentor.textContent = '/year';
    if (subpriceMentor) subpriceMentor.textContent = 'Best value billed yearly';
  }

  billingMonthly.addEventListener('click', setMonthly);
  billingAnnual.addEventListener('click', setAnnual);

  setMonthly();
}

  if (sb) {
    await refreshAuthUI();

    const logoutLink = document.getElementById('nav-logout-link');
    if (logoutLink) {
      logoutLink.addEventListener('click', async (e) => {
        e.preventDefault();
        await sb.auth.signOut();
        showToast('Logged out.');
        await refreshAuthUI();

        const p = window.location.pathname.split('/').pop();
        if (p === 'research-pro.html' || p === 'pricing.html') window.location.href = 'research.html';
      });
    }

    sb.auth.onAuthStateChange(async () => {
      await refreshAuthUI();
    });
  }

  // =============================
  // 3) AUTH PAGE: SHOW ONLY ONE FORM (TOGGLE)
  // =============================
  const showSignInBtn = document.getElementById('showSignIn');
  const showSignUpBtn = document.getElementById('showSignUp');
  const signinForm = document.getElementById('signinForm');
  const signupForm = document.getElementById('signupForm');

  function showSignIn() {
    if (signinForm) signinForm.style.display = 'block';
    if (signupForm) signupForm.style.display = 'none';
    if (showSignInBtn) showSignInBtn.classList.add('active');
    if (showSignUpBtn) showSignUpBtn.classList.remove('active');
  }

  function showSignUp() {
    if (signinForm) signinForm.style.display = 'none';
    if (signupForm) signupForm.style.display = 'block';
    if (showSignInBtn) showSignInBtn.classList.remove('active');
    if (showSignUpBtn) showSignUpBtn.classList.add('active');
  }

  if (showSignInBtn && showSignUpBtn) {
    showSignInBtn.addEventListener('click', (e) => { e.preventDefault(); showSignIn(); });
    showSignUpBtn.addEventListener('click', (e) => { e.preventDefault(); showSignUp(); });
    showSignIn(); // default
  } else {
    // fallback if you didn't add toggle buttons yet:
    // keep both forms as-is (do nothing)
  }

  // Helper: returnTo redirect
  function getReturnTo(defaultUrl = 'research.html') {
    const params = new URLSearchParams(window.location.search);
    return params.get('returnTo') || defaultUrl;
  }

  // Auth submit handlers
  if (sb && signinForm) {
    signinForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const emailEl = document.getElementById('signinEmail');
      const passEl = document.getElementById('signinPassword');
      const email = (emailEl?.value || '').trim();
      const password = passEl?.value || '';

      const { error } = await sb.auth.signInWithPassword({ email, password });
      if (error) return showToast(error.message);

      showToast('Signed in.');
      window.location.href = getReturnTo('research.html');
    });
  }

  if (sb && signupForm) {
    signupForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const nameEl = document.getElementById('signupName');
      const emailEl = document.getElementById('signupEmail');
      const passEl = document.getElementById('signupPassword');

      const full_name = (nameEl?.value || '').trim();
      const email = (emailEl?.value || '').trim();
      const password = passEl?.value || '';

      const { error } = await sb.auth.signUp({
        email,
        password,
        options: { data: { full_name } }
      });

      if (error) return showToast(error.message);

      showToast('Account created. Check email if confirmation is enabled.');
      window.location.href = getReturnTo('research.html');
    });
  }
// =============================
// RESEARCH HUB PAGE (research.html)
// =============================
const researchFeed = document.getElementById('researchFeed');
if (sb && researchFeed) {
  const search = document.getElementById('researchSearch');
  const popularEl = document.getElementById('popularPosts');
  const newsletterBtn = document.getElementById('newsletterBtn');

  // Pull BOTH free + pro for the main feed
  // (manager posts first + newest; your fetchReports currently filters by proOnly)
  // We'll add a new fetchAllReports.
  const all = await fetchAllReports();

  renderResearchRows(researchFeed, all);

  // Popular: top 3 manager posts, else newest
  if (popularEl) {
    const popular = [...all].slice(0, 3);
    renderPopular(popularEl, popular);
  }

  if (search) {
    search.addEventListener('input', () => {
      const q = search.value.toLowerCase().trim();
      const filtered = all.filter(r =>
        (r.title || '').toLowerCase().includes(q) ||
        (r.ticker || '').toLowerCase().includes(q) ||
        (r.summary || '').toLowerCase().includes(q) ||
        (r.content || '').toLowerCase().includes(q)
      );
      renderResearchRows(researchFeed, filtered);
    });
  }

  if (newsletterBtn) {
    newsletterBtn.addEventListener('click', () => {
      showToast('Subscribed (demo).');
    });
  }
}
  // =============================
  // 4) RESEARCH: FREE FEED
  // =============================
  const freeReportsEl = document.getElementById('freeReports');
  if (sb && freeReportsEl) {
    const searchInput = document.getElementById('freeSearch');
    const all = await fetchReports({ proOnly: false });

    renderReports(freeReportsEl, all, { showProBadge: true });

    if (searchInput) {
      searchInput.addEventListener('input', () => {
        const q = searchInput.value.toLowerCase().trim();
        const filtered = all.filter(r =>
          (r.title || '').toLowerCase().includes(q) ||
          (r.ticker || '').toLowerCase().includes(q) ||
          (r.summary || '').toLowerCase().includes(q) ||
          (r.content || '').toLowerCase().includes(q)
        );
        renderReports(freeReportsEl, filtered, { showProBadge: true });
      });
    }
  }

  // =============================
  // 5) RESEARCH: PRO FEED (GATED)
  //     - Upgrade buttons -> pricing.html
  // =============================
  const proReportsEl = document.getElementById('proReports');
  if (sb && proReportsEl) {
    const proGate = document.getElementById('proGate');
    const proSearch = document.getElementById('proSearch');

    const btnMonthly = document.getElementById('btnProMonthly');
    const btnYearly = document.getElementById('btnProYearly');
    const gateMonthly = document.getElementById('gateMonthly');
    const gateYearly = document.getElementById('gateYearly');

    function goToPlans(plan) {
      const returnTo = encodeURIComponent(window.location.pathname.split('/').pop() || 'research-pro.html');
      window.location.href = `pricing.html?plan=${encodeURIComponent(plan)}&returnTo=${returnTo}`;
    }

    if (btnMonthly) btnMonthly.addEventListener('click', () => goToPlans('pro_monthly'));
    if (btnYearly) btnYearly.addEventListener('click', () => goToPlans('pro_yearly'));
    if (gateMonthly) gateMonthly.addEventListener('click', () => goToPlans('pro_monthly'));
    if (gateYearly) gateYearly.addEventListener('click', () => goToPlans('pro_yearly'));

    async function hasProAccess() {
      const { data: { user } } = await sb.auth.getUser();
      if (!user) return false;

      const { data, error } = await sb
        .from('profiles')
        .select('plan, plan_expires_at')
        .eq('id', user.id)
        .single();

      if (error || !data) return false;

      const plan = data.plan || 'free';
      if (!plan.startsWith('pro')) return false;

      if (!data.plan_expires_at) return true;
      return new Date(data.plan_expires_at).getTime() > Date.now();
    }

    let allProCached = [];
    let proSearchWired = false;

    async function loadPro() {
      const allowed = await hasProAccess();

      if (!allowed) {
        if (proGate) proGate.style.display = 'block';
        proReportsEl.innerHTML = '';
        return;
      }

      if (proGate) proGate.style.display = 'none';

      allProCached = await fetchReports({ proOnly: true });
      renderReports(proReportsEl, allProCached, { showProBadge: true });

      if (proSearch && !proSearchWired) {
        proSearchWired = true;
        proSearch.addEventListener('input', () => {
          const q = proSearch.value.toLowerCase().trim();
          const filtered = allProCached.filter(r =>
            (r.title || '').toLowerCase().includes(q) ||
            (r.ticker || '').toLowerCase().includes(q) ||
            (r.summary || '').toLowerCase().includes(q) ||
            (r.content || '').toLowerCase().includes(q)
          );
          renderReports(proReportsEl, filtered, { showProBadge: true });
        });
      }
    }

    await loadPro();
  }

  // =============================
  // 6) PRICING PAGE (PAYMENT PLANS)
  //     - demo checkout: updates profiles plan + expires
  // =============================
  const checkoutMonthly = document.getElementById('checkoutMonthly');
  const checkoutYearly = document.getElementById('checkoutYearly');

  async function requireLoginOrRedirect() {
    if (!sb) return false;

    const { data: { user } } = await sb.auth.getUser();
    if (user) return true;

    const params = new URLSearchParams(window.location.search);
    const plan = params.get('plan') || '';
    const returnTo = params.get('returnTo') || 'research-pro.html';

    // after auth, come back to pricing page
    const backToPricing = `pricing.html?plan=${encodeURIComponent(plan)}&returnTo=${encodeURIComponent(returnTo)}`;
    window.location.href = `auth.html?returnTo=${encodeURIComponent(backToPricing)}`;
    return false;
  }

  async function demoCheckout(plan) {
    if (!sb) return showToast('Supabase not configured.');

    const ok = await requireLoginOrRedirect();
    if (!ok) return;

    const { data: { user } } = await sb.auth.getUser();
    if (!user) return;

    const expires = new Date();
    if (plan === 'pro_monthly') expires.setMonth(expires.getMonth() + 1);
    if (plan === 'pro_yearly') expires.setFullYear(expires.getFullYear() + 1);

    const { error } = await sb
      .from('profiles')
      .update({ plan, plan_expires_at: expires.toISOString() })
      .eq('id', user.id);

    if (error) return showToast(error.message);

    showToast('Payment complete (demo). Pro unlocked.');

    const params = new URLSearchParams(window.location.search);
    const returnTo = params.get('returnTo') || 'research-pro.html';
    window.location.href = returnTo;
  }

  if (checkoutMonthly) checkoutMonthly.addEventListener('click', () => demoCheckout('pro_monthly'));
  if (checkoutYearly) checkoutYearly.addEventListener('click', () => demoCheckout('pro_yearly'));

  // =============================
  // 7) HERO CHART (HOME ONLY)
  // =============================
  const heroCanvas = document.getElementById('heroChart');
  if (heroCanvas) {
    drawHeroChart(heroCanvas);
    window.addEventListener('resize', () => drawHeroChart(heroCanvas));
  }

  // =============================
  // 8) TESTIMONIALS CAROUSEL
  // =============================
  const testimonials = document.querySelectorAll('.testimonial-card');
  const dots = document.querySelectorAll('.dot');
  if (testimonials.length && dots.length) {
    let currentTestimonial = 0;

    function showTestimonial(index) {
      testimonials.forEach(card => card.classList.remove('active'));
      dots.forEach(dot => dot.classList.remove('active'));
      testimonials[index].classList.add('active');
      dots[index].classList.add('active');
    }

    dots.forEach((dot, i) => {
      dot.addEventListener('click', () => {
        currentTestimonial = i;
        showTestimonial(currentTestimonial);
      });
    });

    showTestimonial(0);
    setInterval(() => {
      currentTestimonial = (currentTestimonial + 1) % testimonials.length;
      showTestimonial(currentTestimonial);
    }, 5000);
  }

  // =============================
  // 9) SUBSCRIPTION MODAL (legacy demo)
  // =============================
  const subscriptionModal = document.getElementById('subscription-modal');
  if (subscriptionModal) {
    window.showSubscriptionModal = () => { subscriptionModal.style.display = 'block'; };
    window.closeSubscriptionModal = () => { subscriptionModal.style.display = 'none'; };

    window.addEventListener('click', (e) => {
      if (e.target === subscriptionModal) subscriptionModal.style.display = 'none';
    });

    document.querySelectorAll('.payment-button').forEach(btn => {
      btn.addEventListener('click', () => {
        localStorage.setItem('isSubscribed', 'true');
        if (typeof window.checkSubscriptionStatus === 'function') window.checkSubscriptionStatus();
        showToast('Successfully subscribed to Verdant Apex Premium.');
        subscriptionModal.style.display = 'none';
      });
    });
  }

  // =============================
  // 10) CONTACT FORM
  // =============================
  const contactForm = document.getElementById('contact-form');
  if (contactForm) {
    contactForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const formData = new FormData(contactForm);
      console.log('Contact form submitted:', Object.fromEntries(formData.entries()));
      contactForm.reset();
      showToast('Message sent. Our team will reach out shortly.');
    });
  }

  // =============================
  // 11) INVESTMENT MODEL CREATOR
  // =============================
  const amountRange = document.getElementById('amountRange');
  const yearsRange = document.getElementById('yearsRange');
  const returnRange = document.getElementById('returnRange');

  if (amountRange && yearsRange && returnRange) {
    const amountLabel = document.getElementById('amountLabel');
    const yearsLabel = document.getElementById('yearsLabel');
    const returnLabel = document.getElementById('returnLabel');

    const resultMain = document.getElementById('modelResultMain');
    const resultSub = document.getElementById('modelResultSub');
    const principalSpan = document.getElementById('modelPrincipal');
    const growthSpan = document.getElementById('modelGrowth');
    const riskTag = document.getElementById('modelRiskTag');

    function formatCurrency(val) {
      return '$' + val.toLocaleString(undefined, { maximumFractionDigits: 0 });
    }

    function updateLabels() {
      if (amountLabel) amountLabel.textContent = formatCurrency(Number(amountRange.value));
      if (yearsLabel) yearsLabel.textContent = `${yearsRange.value} years`;
      if (returnLabel) returnLabel.textContent = `${returnRange.value}% CAGR`;
    }

    function updateModel() {
      const amount = Number(amountRange.value);
      const years = Number(yearsRange.value);
      const rate = Number(returnRange.value) / 100;

      const finalValue = amount * Math.pow(1 + rate, years);
      const growth = finalValue - amount;

      if (resultMain) resultMain.textContent = formatCurrency(Math.round(finalValue));
      if (resultSub) resultSub.textContent = `Projected value assuming ${returnRange.value}% annualized over ${years} years (no additional contributions).`;
      if (principalSpan) principalSpan.textContent = formatCurrency(amount);
      if (growthSpan) growthSpan.textContent = formatCurrency(Math.round(growth));

      let riskText = 'Low–Moderate risk profile';
      if (rate >= 0.15) riskText = 'Aggressive risk profile';
      else if (rate >= 0.10) riskText = 'Balanced growth profile';
      if (riskTag) riskTag.textContent = riskText;
    }

    [amountRange, yearsRange, returnRange].forEach(slider => {
      slider.addEventListener('input', () => {
        updateLabels();
        updateModel();
      });
    });

    updateLabels();
    updateModel();
  }

  // =============================
  // 12) PORTFOLIO BUILDER
  // =============================
  const addAssetBtn = document.getElementById('add-asset-btn');
  if (addAssetBtn) {
    const tickerInput = document.getElementById('assetTicker');
    const weightInput = document.getElementById('assetWeight');
    const riskInput = document.getElementById('assetRisk');
    const tableBody = document.getElementById('portfolioBody');
    const totalSpan = document.getElementById('portfolioTotal');
    const totalStatus = document.getElementById('portfolioTotalStatus');
    const avgRiskSpan = document.getElementById('portfolioAvgRisk');

    let assets = [];

    function renderPortfolio() {
      if (!tableBody) return;
      tableBody.innerHTML = '';

      let totalWeight = 0;
      let weightedRisk = 0;

      assets.forEach((asset, index) => {
        totalWeight += asset.weight;
        weightedRisk += asset.weight * asset.risk;

        const row = document.createElement('tr');
        row.innerHTML = `
          <td>${escapeHtml(asset.ticker)}</td>
          <td>${asset.weight.toFixed(1)}%</td>
          <td>${asset.risk.toFixed(1)}</td>
          <td><button data-index="${index}">Remove</button></td>
        `;
        tableBody.appendChild(row);
      });

      if (totalSpan) totalSpan.textContent = totalWeight.toFixed(1) + '%';

      const avgRisk = totalWeight > 0 ? (weightedRisk / totalWeight) : 0;
      if (avgRiskSpan) avgRiskSpan.textContent = avgRisk.toFixed(1);

      if (totalStatus) {
        if (Math.abs(totalWeight - 100) < 0.0001) {
          totalStatus.textContent = 'Perfect – allocations sum to 100%.';
          totalStatus.className = 'total-ok';
        } else {
          totalStatus.textContent = 'Adjust until total weight equals 100%.';
          totalStatus.className = 'total-bad';
        }
      }

      // Remove buttons
      tableBody.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => {
          const idx = Number(btn.getAttribute('data-index'));
          assets.splice(idx, 1);
          renderPortfolio();
        });
      });
    }

    addAssetBtn.addEventListener('click', () => {
      const ticker = (tickerInput?.value || '').trim().toUpperCase();
      const weight = Number(weightInput?.value);
      const risk = Number(riskInput?.value);

      if (!ticker) return showToast('Please enter a ticker.');
      if (isNaN(weight) || weight <= 0) return showToast('Weight must be a positive number.');
      if (isNaN(risk) || risk < 1 || risk > 10) return showToast('Risk score must be between 1 and 10.');

      assets.push({ ticker, weight, risk });

      if (tickerInput) tickerInput.value = '';
      if (weightInput) weightInput.value = '';
      if (riskInput) riskInput.value = '5';

      renderPortfolio();
    });

    renderPortfolio();
  }

  // =============================
  // 13) SOLUTIONS ACCORDION
  // =============================
  const accordionHeaders = document.querySelectorAll('.accordion-header');
  if (accordionHeaders.length) {
    accordionHeaders.forEach(header => {
      header.addEventListener('click', () => {
        const body = header.nextElementSibling;
        if (!body) return;

        const isOpen = body.classList.contains('open');
        if (isOpen) {
          body.style.maxHeight = null;
          body.classList.remove('open');
        } else {
          body.style.maxHeight = body.scrollHeight + 'px';
          body.classList.add('open');
        }
      });
    });
  }

  // =============================
  // 14) SIMPLE SUBSCRIPTION CHECK (legacy overlay)
  // =============================
  window.checkSubscriptionStatus = function () {
    const isSubscribed = localStorage.getItem('isSubscribed') === 'true';
    const overlay = document.getElementById('unlock-overlay');
    if (!overlay) return;
    overlay.style.display = isSubscribed ? 'none' : 'flex';
  };

  if (document.getElementById('unlock-overlay')) {
    window.checkSubscriptionStatus();
  }
});


// =============================
// HERO CHART
// =============================
function drawHeroChart(canvas) {
  const ctx = canvas.getContext('2d');
  const width = canvas.width = canvas.offsetWidth;
  const height = canvas.height = canvas.offsetHeight;

  ctx.clearRect(0, 0, width, height);

  // background
  ctx.fillStyle = '#02120D';
  ctx.fillRect(0, 0, width, height);

  // grid
  ctx.strokeStyle = 'rgba(255,255,255,0.06)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = (height / 4) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  // data
  const points = 40;
  let value = 100;
  const data = [];
  for (let i = 0; i < points; i++) {
    value += (Math.random() - 0.2) * 4;
    data.push(Math.max(85, Math.min(130, value)));
  }

  ctx.strokeStyle = '#22C55E';
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  data.forEach((val, idx) => {
    const x = (width / (points - 1)) * idx;
    const y = height - ((val - 85) / 45) * height;
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}


// =============================
// TOAST
// =============================
function showToast(message) {
  const toast = document.getElementById('toast');
  const toastMessage = document.getElementById('toast-message');
  if (!toast || !toastMessage) return;

  toastMessage.textContent = message;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 3000);
}


// =============================
// RESEARCH HELPERS
// =============================
async function fetchReports({ proOnly }) {
  const sb = window.supabaseClient;
  if (!sb) return [];

  // Manager posts first, then newest first
  let query = sb
    .from('research_reports')
    .select('id,title,ticker,summary,content,is_pro,is_manager_post,created_at')
    .order('is_manager_post', { ascending: false })
    .order('created_at', { ascending: false });

  query = proOnly ? query.eq('is_pro', true) : query.eq('is_pro', false);

  const { data, error } = await query;
  if (error) {
    showToast(error.message);
    return [];
  }
  return data || [];
}

function renderReports(container, reports, { showProBadge } = {}) {
  container.innerHTML = '';

  if (!reports.length) {
    container.innerHTML = `<div style="color:var(--gray-600);">No reports found.</div>`;
    return;
  }

  reports.forEach(r => {
    const created = r.created_at ? new Date(r.created_at).toLocaleDateString() : '';
    const badge = (showProBadge && r.is_pro)
      ? `<span class="research-badge">PRO</span>`
      : `<span class="research-badge">FREE</span>`;

    const ticker = r.ticker
      ? `<span class="research-ticker">${escapeHtml(r.ticker)}</span>`
      : `<span class="research-ticker">Research</span>`;

    const title = escapeHtml(r.title || 'Untitled report');
    const summary = escapeHtml(r.summary || '').slice(0, 220);
    const contentPreview = escapeHtml(r.content || '').slice(0, 220);

    const card = document.createElement('div');
    card.className = 'research-card';
    card.innerHTML = `
      <div class="research-meta">
        ${ticker}
        ${badge}
      </div>
      <div class="research-title">${title}</div>
      <div class="research-summary">${summary || contentPreview || '—'}</div>
      <div class="research-date">${created}</div>
    `;
    container.appendChild(card);
  });
}

function escapeHtml(str) {
  return String(str)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}
async function fetchAllReports() {
  const sb = window.supabaseClient;
  if (!sb) return [];

  const { data, error } = await sb
    .from('research_reports')
    .select('id,title,ticker,summary,content,is_pro,is_manager_post,created_at,thumbnail_url')
    .order('is_manager_post', { ascending: false })
    .order('created_at', { ascending: false });

  if (error) {
    showToast(error.message);
    return [];
  }
  return data || [];
}

function renderResearchRows(container, reports) {
  container.innerHTML = '';
  if (!reports.length) {
    container.innerHTML = `<div style="color:var(--gray-600);">No posts found.</div>`;
    return;
  }

  reports.forEach(r => {
    const dateStr = r.created_at ? new Date(r.created_at).toLocaleDateString() : '';
    const isPro = !!r.is_pro;

    const thumb = r.thumbnail_url
      ? `<img src="${escapeHtml(r.thumbnail_url)}" alt="">`
      : `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--gray-500);font-weight:800;">Research</div>`;

    const excerpt = (r.summary || r.content || '').toString().trim();
    const shortExcerpt = escapeHtml(excerpt).slice(0, 190) + (excerpt.length > 190 ? '…' : '');

    const title = escapeHtml(r.title || 'Untitled');
    const tag = isPro ? `<span class="tag-pill pro">PRO</span>` : `<span class="tag-pill">FREE</span>`;

    const readMoreHref = isPro ? 'research-pro.html' : 'research-free.html';

    const row = document.createElement('article');
    row.className = 'post-row';
    row.innerHTML = `
      <div class="post-thumb">${thumb}</div>
      <div>
        <div class="post-meta">
          <span class="date-pill"><i class="far fa-calendar"></i> ${dateStr}</span>
          ${tag}
          ${r.ticker ? `<span class="tag-pill">${escapeHtml(r.ticker)}</span>` : ''}
        </div>
        <h2 class="post-title">${title}</h2>
        <div class="post-excerpt">${shortExcerpt || '—'}</div>
        <a class="readmore" href="${readMoreHref}">
          Read More <i class="fas fa-arrow-right"></i>
        </a>
      </div>
    `;
    container.appendChild(row);
  });
}

function renderPopular(container, reports) {
  container.innerHTML = '';
  if (!reports.length) {
    container.innerHTML = `<div style="color:var(--gray-600);">No posts yet.</div>`;
    return;
  }

  reports.forEach(r => {
    const dateStr = r.created_at ? new Date(r.created_at).toLocaleDateString() : '';
    const thumb = r.thumbnail_url
      ? `<img src="${escapeHtml(r.thumbnail_url)}" alt="">`
      : `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--gray-500);font-weight:800;">—</div>`;

    const item = document.createElement('div');
    item.className = 'popular-item';
    item.innerHTML = `
      <div class="popular-thumb">${thumb}</div>
      <div>
        <div class="popular-date">${dateStr}</div>
        <div class="popular-title">${escapeHtml(r.title || 'Untitled')}</div>
      </div>
    `;
    container.appendChild(item);
  });
}


async function initProResearchGate() {
  // Only run on the pro page
  const isProPage =
    window.location.pathname.endsWith("research-pro.html") ||
    window.location.pathname.includes("research-pro.html");

  if (!isProPage) return;

  const wrap = document.getElementById("proLockedWrap");
  const overlay = document.getElementById("proLockOverlay");

  const btnMonthlyTop = document.getElementById("btnProMonthly");
  const btnYearlyTop = document.getElementById("btnProYearly");

  const btnMonthly = document.getElementById("proLockMonthly");
  const btnYearly = document.getElementById("proLockYearly");
  const btnSignIn = document.getElementById("proLockSignIn");

  const lockText = document.getElementById("proLockText");

  // Safety
  if (!wrap || !overlay) return;

  // Where your pricing lives:
  const PRICING_PAGE = "memberships.html";

  function goPricing(billing) {
    // Save intent so pricing page can pre-select + subscribe
    sessionStorage.setItem("pending_plan", "pro");
    sessionStorage.setItem("pending_billing", billing); // "monthly" or "annual"
    window.location.href = `${PRICING_PAGE}?plan=pro&billing=${billing}`;
  }

  function goSignInThenPricing() {
    // Send them to sign in, then back to pricing
    sessionStorage.setItem("post_auth_redirect", `${PRICING_PAGE}?plan=pro`);
    window.location.href = `auth.html?redirect=${encodeURIComponent(`${PRICING_PAGE}?plan=pro`)}`;
  }

  function lockPage(message) {
    wrap.classList.add("pro-locked");
    overlay.classList.add("active");
    overlay.setAttribute("aria-hidden", "false");
    if (lockText && message) lockText.textContent = message;
  }

  function unlockPage() {
    wrap.classList.remove("pro-locked");
    overlay.classList.remove("active");
    overlay.setAttribute("aria-hidden", "true");
  }

  // Button wiring
  if (btnMonthlyTop) btnMonthlyTop.addEventListener("click", () => goPricing("monthly"));
  if (btnYearlyTop) btnYearlyTop.addEventListener("click", () => goPricing("annual"));
  if (btnMonthly) btnMonthly.addEventListener("click", () => goPricing("monthly"));
  if (btnYearly) btnYearly.addEventListener("click", () => goPricing("annual"));
  if (btnSignIn) btnSignIn.addEventListener("click", goSignInThenPricing);

  // --- AUTH + SUBSCRIPTION CHECK ---
  // Assumes `supabase` exists globally from supabaseClient.js
  let user = null;

  try {
    const { data, error } = await supabase.auth.getUser();
    if (!error) user = data?.user || null;
  } catch (e) {
    user = null;
  }

  // If not logged in → lock + tell them to sign in
  if (!user) {
    lockPage("Please sign in, then upgrade to unlock Pro Research.");
    return;
  }

  // Logged in → check subscription
  // Recommended: store this in a `profiles` row, e.g. { id, plan: 'pro', pro_active: true }
  // OR a `subscriptions` table. This code tries profiles first.
  let hasPro = false;

  try {
    const { data: profile, error } = await supabase
      .from("profiles")
      .select("plan, pro_active, subscription_status")
      .eq("id", user.id)
      .single();

    if (!error && profile) {
      // Accept several common patterns:
      if (profile.pro_active === true) hasPro = true;
      if ((profile.plan || "").toLowerCase() === "pro") hasPro = true;
      if ((profile.subscription_status || "").toLowerCase() === "active") hasPro = true;
    }
  } catch (e) {
    hasPro = false;
  }

  if (!hasPro) {
    lockPage("Upgrade to Pro to unlock full research reports.");
    return;
  }

  // Subscribed → unlock
  unlockPage();
}

// run after your other init code
document.addEventListener("DOMContentLoaded", () => {
  initProResearchGate();
});


/* ===========================
   PRO RESEARCH GATE + PRICING GUARD
   =========================== */

function _currentPage() {
  const p = (window.location.pathname || "").toLowerCase();
  return p.substring(p.lastIndexOf("/") + 1);
}

function _qs(name) {
  return new URLSearchParams(window.location.search).get(name);
}

async function _getUserSafe() {
  try {
    const { data, error } = await supabase.auth.getUser();
    if (error) return null;
    return data?.user || null;
  } catch {
    return null;
  }
}

/**
 * You MUST adapt this to your schema.
 * This checks `profiles` for one of:
 * - pro_active === true
 * - plan === 'pro'
 * - subscription_status === 'active'
 */
async function _hasProSubscription(userId) {
  try {
    const { data: profile, error } = await supabase
      .from("profiles")
      .select("plan, pro_active, subscription_status")
      .eq("id", userId)
      .single();

    if (error || !profile) return false;

    if (profile.pro_active === true) return true;
    if ((profile.plan || "").toLowerCase() === "pro") return true;
    if ((profile.subscription_status || "").toLowerCase() === "active") return true;

    return false;
  } catch {
    return false;
  }
}

/* ---------- PRO PAGE: blur + upgrade popup ---------- */
async function initProResearchGate() {
  const page = _currentPage();
  const isProPage = page === "research-pro.html";
  if (!isProPage) return;

  const wrap = document.getElementById("proLockedWrap");
  const overlay = document.getElementById("proLockOverlay");

  const btnMonthlyTop = document.getElementById("btnProMonthly");
  const btnYearlyTop = document.getElementById("btnProYearly");

  const btnMonthly = document.getElementById("proLockMonthly");
  const btnYearly = document.getElementById("proLockYearly");
  const btnSignIn = document.getElementById("proLockSignIn");
  const lockText = document.getElementById("proLockText");

  if (!wrap || !overlay) return;

  const PRICING_PAGE = "pricing.html";

  function lockPage(message) {
    wrap.classList.add("pro-locked");
    overlay.classList.add("active");
    overlay.setAttribute("aria-hidden", "false");
    if (lockText && message) lockText.textContent = message;
  }

  function unlockPage() {
    wrap.classList.remove("pro-locked");
    overlay.classList.remove("active");
    overlay.setAttribute("aria-hidden", "true");
  }

  function goPricing(billing) {
    // store intent so pricing page can pre-select + subscribe
    sessionStorage.setItem("pending_plan", "pro");
    sessionStorage.setItem("pending_billing", billing); // "monthly" | "annual"
    window.location.href = `${PRICING_PAGE}?plan=pro&billing=${billing}`;
  }

  function goSignInThenPricing() {
    sessionStorage.setItem("post_auth_redirect", `${PRICING_PAGE}?plan=pro`);
    window.location.href = `auth.html?redirect=${encodeURIComponent(`${PRICING_PAGE}?plan=pro`)}`;
  }

  // Wire buttons
  if (btnMonthlyTop) btnMonthlyTop.addEventListener("click", () => goPricing("monthly"));
  if (btnYearlyTop) btnYearlyTop.addEventListener("click", () => goPricing("annual"));
  if (btnMonthly) btnMonthly.addEventListener("click", () => goPricing("monthly"));
  if (btnYearly) btnYearly.addEventListener("click", () => goPricing("annual"));
  if (btnSignIn) btnSignIn.addEventListener("click", goSignInThenPricing);

  // Auth check
  const user = await _getUserSafe();
  if (!user) {
    lockPage("Please sign in, then upgrade to unlock Pro Research.");
    return;
  }

  // Subscription check
  const hasPro = await _hasProSubscription(user.id);
  if (!hasPro) {
    lockPage("Upgrade to Pro to unlock full research reports.");
    return;
  }

  unlockPage();
}

/* ---------- PRICING PAGE: require login before subscribe + preselect billing ---------- */
async function initPricingAuthGuardAndPrefill() {
  const page = _currentPage();
  const isPricingPage = page === "pricing.html";
  if (!isPricingPage) return;

  // These IDs MUST exist on pricing.html, or update them here
  const btnSubscribePro = document.getElementById("subscribePro");
  const btnSubscribeMentor = document.getElementById("subscribeMentor");

  // Billing toggle IDs (from your sample)
  const billingMonthlyBtn = document.getElementById("billingMonthly");
  const billingAnnualBtn = document.getElementById("billingAnnual");

  function selectBilling(billing) {
    // clicks your existing UI buttons so your existing pricing logic runs
    if (billing === "annual") {
      if (billingAnnualBtn) billingAnnualBtn.click();
    } else {
      if (billingMonthlyBtn) billingMonthlyBtn.click();
    }
  }

  // Preselect plan/billing from query string or sessionStorage intent
  const plan = (_qs("plan") || sessionStorage.getItem("pending_plan") || "").toLowerCase();
  const billing = (_qs("billing") || sessionStorage.getItem("pending_billing") || "monthly").toLowerCase();

  // Preselect billing UI
  selectBilling(billing === "annual" ? "annual" : "monthly");

  // If user is not logged in and they came intending to subscribe, force sign-in
  const user = await _getUserSafe();
  if (!user && (plan === "pro" || plan === "mentor")) {
    sessionStorage.setItem("post_auth_redirect", window.location.href.replace(window.location.origin, ""));
    window.location.href = `auth.html?redirect=${encodeURIComponent(window.location.href.replace(window.location.origin, ""))}`;
    return;
  }

  async function requireLoginOrRedirect(planName) {
    const u = await _getUserSafe();
    if (u) return true;

    sessionStorage.setItem("pending_plan", planName);
    sessionStorage.setItem("pending_billing", billing === "annual" ? "annual" : "monthly");
    sessionStorage.setItem("post_auth_redirect", "pricing.html" + window.location.search);
    window.location.href = `auth.html?redirect=${encodeURIComponent("pricing.html" + window.location.search)}`;
    return false;
  }

  // Guard subscribe buttons
  if (btnSubscribePro) {
    btnSubscribePro.addEventListener("click", async (e) => {
      const ok = await requireLoginOrRedirect("pro");
      if (!ok) e.preventDefault();
    });
  }

  if (btnSubscribeMentor) {
    btnSubscribeMentor.addEventListener("click", async (e) => {
      const ok = await requireLoginOrRedirect("mentor");
      if (!ok) e.preventDefault();
    });
  }

  // Cleanup intent once on pricing page (optional)
  sessionStorage.removeItem("pending_plan");
  sessionStorage.removeItem("pending_billing");
}

/* ---------- run ---------- */
document.addEventListener("DOMContentLoaded", () => {
  initProResearchGate();
  initPricingAuthGuardAndPrefill();
});

document.getElementById("publishPost").addEventListener("click", async () => {

  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return alert("Sign in first");

  const title = document.getElementById("postTitle").value;
  const content = document.getElementById("postContent").value;

  const { error } = await supabase
    .from("pro_posts")
    .insert([{ title, content, author_id: user.id }]);

  if (error) alert(error.message);
  else alert("Post published");
});

async function loadProPosts() {
  const { data, error } = await supabase
    .from("pro_posts")
    .select("*")
    .order("created_at", { ascending: false });

  console.log(data);
}

createProPost();