/* Portfolio front end. No dependencies and no build step.

   Content comes from window.PORTFOLIO (data/portfolio.js). Source excerpts come
   from window.PORTFOLIO_PREVIEWS and PORTFOLIO_MANIFESTS (data/previews.js,
   written by tools/protect.py). The full source of a gated file is not on the
   site, so there is nothing here to fetch or unblur. */
(function () {
  "use strict";

  var DATA = window.PORTFOLIO || {};
  var PREVIEWS = window.PORTFOLIO_PREVIEWS || {};
  var MANIFESTS = window.PORTFOLIO_MANIFESTS || {};
  var profile = DATA.profile || {};
  var approach = DATA.approach || {};
  var toolkit = DATA.toolkit || [];
  var projects = DATA.projects || [];

  /* singular, plural */
  var KIND = {
    app: ["Application", "Applications"],
    algorithm: ["Algorithm", "Algorithms"],
    code: ["Code", "Code"],
    website: ["Website", "Websites"],
    document: ["Research", "Research"],
    research: ["Research", "Research"],
    design: ["Design", "Design"],
    data: ["Data", "Data"],
    other: ["Project", "Other"]
  };
  var WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];

  var ICON = {
    arrow: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 10h13.5M11.5 5l5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>',
    out: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 14 14 6M7.5 6H14v6.5" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>'
  };

  /* Toolkit entries are a flat list in the data file; they are grouped here.
     Anything unrecognised lands in the last group. */
  var TOOL_GROUPS = [
    ["Languages", /^(python|javascript|typescript|html.*|css|sql|r|c|c\+\+|c#|java|go|rust|vba|matlab|julia|bash|excel vba)$/i],
    ["Quantitative methods", /monte carlo|black.?scholes|greeks|volatility|garch|arima|regression|backtest|stochastic|time series|risk|\bvar\b|optimi[sz]|statistic|econometric|valuation|dcf|kelly|bootstrap/i],
    ["Libraries", /numpy|pandas|scipy|matplotlib|pyqt|tkinter|plotly|statsmodels|scikit|sklearn|torch|tensorflow|numba|polars|seaborn|react|d3|chart\.js/i],
    ["Data and tooling", /./]
  ];

  /* ------------------------------------------------------------- helpers */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function icon(name) {
    var holder = document.createElement("span");
    holder.innerHTML = ICON[name];
    return holder.firstChild;
  }
  function setText(sel, text) {
    var n = $(sel);
    if (n) n.textContent = text || "";
  }
  function each(list, fn) { Array.prototype.forEach.call(list, fn); }
  function nfmt(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }
  function pad2(n) { return n < 10 ? "0" + n : String(n); }
  function kindOf(p) { return KIND[p.kind] || KIND.other; }
  function isDocument(p) { return p.kind === "document" || p.kind === "research"; }
  function fileName(path) { return String(path).split("/").pop(); }
  function ext(path) {
    var m = /\.([a-z0-9]+)$/i.exec(path);
    return m ? m[1].toLowerCase() : "";
  }
  function codePath(c) { return typeof c === "string" ? c : c.path; }

  function img(src, alt) {
    var im = new Image();
    im.decoding = "async";
    im.loading = "lazy";
    im.alt = alt || "";
    im.src = src;
    return im;
  }

  function outLink(url, label) {
    var a = el("a", "textlink textlink--out", label);
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener";
    a.appendChild(icon("out"));
    return a;
  }

  function imagesOf(p) {
    if (p.images && p.images.length) return p.images.slice();
    return p.cover ? [p.cover] : [];
  }

  /* "screenshot-volatility-surface.png" -> "Volatility surface" */
  function captionFor(src, p) {
    var base = fileName(src).replace(/\.[a-z0-9]+$/i, "");
    var page = /^page[-_ ]?0*(\d+)$/i.exec(base);
    if (page) return "Page " + page[1];
    if (/^(cover|home|index|hero)$/i.test(base)) return p.kind === "website" ? "Home page" : "Overview";
    base = base.replace(/^(screenshot|screen|shot|capture|image|img)[-_ ]*/i, "")
               .replace(/[-_]+/g, " ").trim();
    return base ? base.charAt(0).toUpperCase() + base.slice(1) : "Screenshot";
  }

  /* Featured projects first, the rest after, in data-file order. */
  var featured = projects.filter(function (p) { return p.featured; });
  var others = projects.filter(function (p) { return !p.featured; });
  if (!featured.length) {             // nothing featured: show the first three in depth
    featured = others.slice(0, 3);
    others = others.slice(3);
  }
  var ordered = featured.concat(others);

  /* -------------------------------------------------------- line counts */
  var PY_EXT = { py: 1, pyw: 1 };
  var WEB_EXT = { html: 1, htm: 1, css: 1, js: 1, mjs: 1, ts: 1, jsx: 1, tsx: 1 };

  /* Every file the site knows the length of, once each. */
  function sourceFiles(p) {
    var seen = {}, out = [];
    (p.code || []).forEach(function (c) {
      var path = codePath(c), rec = PREVIEWS[path];
      if (rec && !seen[path]) { seen[path] = 1; out.push({ path: path, lines: rec.totalLines }); }
    });
    var man = MANIFESTS[p.id];
    ((man && man.files) || []).forEach(function (f) {
      var path = "projects/" + p.id + "/" + f.name;
      if (!seen[path]) { seen[path] = 1; out.push({ path: path, lines: f.lines }); }
    });
    return out;
  }

  function lineCounts(p) {
    var c = { python: 0, web: 0, total: 0 };
    sourceFiles(p).forEach(function (f) {
      var e = ext(f.path);
      if (PY_EXT[e]) c.python += f.lines;
      else if (WEB_EXT[e]) c.web += f.lines;
      else return;
      c.total += f.lines;
    });
    return c;
  }

  /* ------------------------------------------------- syntax highlighting */
  var KW = ("abstract as assert async await break case catch class const continue " +
    "def default del elif else except export extends final finally for from function " +
    "global if implements import in interface is lambda let match new nil None not null or " +
    "package pass private protected public raise return self static struct super switch this throw " +
    "True False true false try typeof var void while with yield and enum fn impl pub where").split(" ");
  var KWSET = {};
  KW.forEach(function (k) { KWSET[k] = 1; });

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function highlight(src) {
    var out = "", last = 0, m;
    var re = /(\/\*[\s\S]*?\*\/|(?:^|\s)#[^\n]*|\/\/[^\n]*|<!--[\s\S]*?-->)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)|(\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|([A-Za-z_$][\w$]*)/g;
    while ((m = re.exec(src)) !== null) {
      out += esc(src.slice(last, m.index));
      last = re.lastIndex;
      if (m[1]) out += '<span class="tok-com">' + esc(m[1]) + "</span>";
      else if (m[2]) out += '<span class="tok-str">' + esc(m[2]) + "</span>";
      else if (m[3]) out += '<span class="tok-num">' + esc(m[3]) + "</span>";
      else if (KWSET[m[4]]) out += '<span class="tok-kw">' + esc(m[4]) + "</span>";
      else if (src[re.lastIndex] === "(") out += '<span class="tok-fn">' + esc(m[4]) + "</span>";
      else out += esc(m[4]);
    }
    return out + esc(src.slice(last));
  }

  /* READMEs: tint the structure (headings, quotes, code), never English words. */
  function tintMarkdown(src) {
    var fence = false;
    return src.split("\n").map(function (line) {
      if (/^\s*```/.test(line)) { fence = !fence; return '<span class="tok-com">' + esc(line) + "</span>"; }
      if (fence) return '<span class="tok-str">' + esc(line) + "</span>";
      if (/^\s{0,3}#/.test(line)) return '<span class="tok-kw">' + esc(line) + "</span>";
      if (/^\s{0,3}>/.test(line)) return '<span class="tok-com">' + esc(line) + "</span>";
      return esc(line).replace(/`([^`\n]+)`/g, '<span class="tok-str">`$1`</span>');
    }).join("\n");
  }

  /* A real excerpt of the project's code, standing in where there is no screenshot. */
  function firstExcerpt(p) {
    var code = p.code || [];
    for (var i = 0; i < code.length; i++) {
      var rec = PREVIEWS[codePath(code[i])];
      if (rec && rec.preview && /^(python|javascript|typescript|html|css)$/.test(rec.lang)) return rec;
    }
    return null;
  }

  function codeTile(p, lines) {
    var rec = firstExcerpt(p);
    var tile = el("div", "codetile");
    tile.setAttribute("aria-hidden", "true");
    var pre = el("pre");
    pre.innerHTML = highlight(rec ? rec.preview.split("\n").slice(0, lines).join("\n") : "");
    tile.appendChild(pre);
    if (rec) tile.appendChild(el("span", "codetile__name", rec.name));
    return tile;
  }

  function metricsList(metrics) {
    var ul = el("ul", "metrics");
    metrics.forEach(function (m) {
      var li = el("li");
      li.appendChild(el("strong", null, m.value));
      li.appendChild(el("span", null, m.label));
      ul.appendChild(li);
    });
    return ul;
  }

  /* ================================================================ hero */
  function renderHero() {
    var name = profile.name || "Portfolio";
    document.title = name + " · " + (profile.kicker || "Portfolio");
    each(document.querySelectorAll("[data-name]"), function (n) { n.textContent = name; });

    /* The small line under the name is spread letter by letter to the name's width. */
    var sub = $("#lockup-sub");
    var word = sub.textContent.trim();
    sub.textContent = "";
    word.split("").forEach(function (ch) { sub.appendChild(el("span", null, ch)); });

    setText("#hero-eyebrow", profile.kicker || "");
    var head = profile.headline || {};
    setText("#head-lead", head.lead || name);
    setText("#head-accent", head.accent || "");
    setText("#hero-intro", profile.intro || "");

    if (profile.status) {
      setText("#hero-status", profile.status);
      $("#hero-status").hidden = false;
    }

    var second = $("#hero-second");
    if (profile.resume) {
      second.textContent = "Résumé (PDF)";
      second.href = profile.resume;
      second.target = "_blank";
      second.rel = "noopener";
    }

    if (profile.github) {
      var gh = $("#nav-github");
      gh.href = profile.github;
      gh.hidden = false;
    }
  }

  function renderPrinciples() {
    var points = approach.points || [];
    var list = $("#principles");
    if (!points.length) { list.parentNode.hidden = true; return; }
    list.style.setProperty("--n", Math.min(points.length, 4));
    points.forEach(function (pt, i) {
      var li = el("li");
      li.appendChild(el("span", "n", pad2(i + 1)));
      li.appendChild(el("h3", null, pt.title));
      if (pt.body) li.appendChild(el("p", null, pt.body));
      list.appendChild(li);
    });
  }

  /* ========================================================== the work */
  var figureNo = 1;            // Fig. 1 is the simulation in the hero

  function caseFigure(p) {
    var fig = el("figure", "case__figure");
    var plate = el("button", "plate");
    plate.type = "button";
    plate.setAttribute("aria-label", "Open " + p.title);
    var images = imagesOf(p), caption;

    if (isDocument(p) && images.length) {
      var pages = el("div", "pages" + (images.length === 1 ? " pages--single" : ""));
      /* back left, back right, then the cover on top */
      var stack = images.length >= 3 ? [images[1], images[2], images[0]] : images.slice().reverse();
      stack.forEach(function (src) { pages.appendChild(img(src, "")); });
      plate.appendChild(pages);
      caption = (images.length > 1 ? "Cover and selected pages, " : "Cover, ") + p.title;
    } else if (images.length) {
      var src = p.cover || images[0];
      var frame = el("div", "plate__frame");
      var im = img(src, p.title + ", " + captionFor(src, p).toLowerCase());
      frame.style.aspectRatio = "16 / 9";
      im.addEventListener("load", function () {
        if (im.naturalWidth) frame.style.aspectRatio = im.naturalWidth + " / " + im.naturalHeight;
      });
      frame.appendChild(im);
      plate.appendChild(frame);
      caption = captionFor(src, p) + ", " + p.title;
    } else {
      plate.appendChild(codeTile(p, 24));
      caption = "Source excerpt, " + p.title;
    }

    plate.addEventListener("click", function () { openSheet(p); });
    fig.appendChild(plate);
    var cap = el("figcaption", "plate-cap");
    figureNo += 1;
    cap.appendChild(el("span", "fig-no", "Fig. " + figureNo));
    cap.appendChild(el("span", null, caption));
    fig.appendChild(cap);
    return fig;
  }

  function caseText(p, no) {
    var t = el("div", "case__text");
    var kicker = el("p", "case__kicker");
    kicker.appendChild(el("span", "no", pad2(no)));
    kicker.appendChild(el("span", null, [kindOf(p)[0], p.date].filter(Boolean).join(" · ")));
    t.appendChild(kicker);
    t.appendChild(el("h3", "case__title", p.title));
    if (p.summary) t.appendChild(el("p", "case__summary", p.summary));
    if (p.metrics && p.metrics.length) t.appendChild(metricsList(p.metrics));
    if (p.tags && p.tags.length) {
      var stack = el("p", "case__stack");
      stack.appendChild(el("b", null, isDocument(p) ? "Topics " : "Built with "));
      stack.appendChild(document.createTextNode(p.tags.join(", ")));
      t.appendChild(stack);
    }
    var actions = el("div", "case__actions");
    var read = el("button", "textlink", isDocument(p) ? "Open the paper" : "Read the case study");
    read.type = "button";
    read.appendChild(icon("arrow"));
    read.addEventListener("click", function () { openSheet(p); });
    actions.appendChild(read);
    if (p.demo) actions.appendChild(outLink(p.demo, "Open the live build"));
    t.appendChild(actions);
    return t;
  }

  function renderWork() {
    var box = $("#cases");
    if (!featured.length) { $("#work").hidden = true; return; }
    featured.forEach(function (p, i) {
      var art = el("article", "case" + (i % 2 ? " case--flip" : ""));
      art.setAttribute("aria-label", p.title);
      art.appendChild(caseFigure(p));
      art.appendChild(caseText(p, i + 1));
      box.appendChild(art);
    });

    var n = featured.length;
    setText("#work-note", (WORDS[n] || n) + " project" + (n === 1 ? "" : "s") +
      " in depth. Each opens to the full write-up, screenshots and an excerpt of the source.");

    /* Factsheet: totals computed from the files the site actually lists. */
    var py = 0, web = 0;
    projects.forEach(function (p) {
      var c = lineCounts(p);
      py += c.python;
      web += c.web;
    });
    var rows = [["Projects", nfmt(projects.length), ""]];
    if (py) rows.push(["Python", nfmt(py), "lines"]);
    if (web) rows.push(["JavaScript, HTML, CSS", nfmt(web), "lines"]);
    /* Research is counted in pages when a paper lists them as a metric. */
    var docs = projects.filter(isDocument), pages = 0;
    docs.forEach(function (p) {
      (p.metrics || []).forEach(function (m) {
        var v = String(m.value).replace(/,/g, "");
        if (/^pages\b/i.test(m.label || "") && /^\d+$/.test(v)) pages += parseInt(v, 10);
      });
    });
    if (pages) rows.push(["Research", nfmt(pages), "pages"]);
    else if (docs.length) rows.push(["Research papers", String(docs.length), ""]);
    var sheetEl = $("#factsheet");
    rows.forEach(function (r) {
      var d = el("div");
      d.appendChild(el("dt", null, r[0]));
      var dd = el("dd", null, r[1]);
      if (r[2]) dd.appendChild(el("small", null, r[2]));
      d.appendChild(dd);
      sheetEl.appendChild(d);
    });
  }

  function ledgerRow(p, no) {
    var li = el("li", "ledger__row");
    li.setAttribute("data-group", kindOf(p)[1]);
    var b = el("button", "ledger__btn");
    b.type = "button";
    b.setAttribute("aria-label", p.title + ", " + kindOf(p)[0].toLowerCase() + (p.date ? ", " + p.date : ""));

    b.appendChild(el("span", "ledger__no", pad2(no)));
    var thumb = el("span", "ledger__thumb");
    var cover = p.cover || imagesOf(p)[0];
    thumb.appendChild(cover ? img(cover, "") : codeTile(p, 16));
    b.appendChild(thumb);

    var main = el("span", "ledger__main");
    main.appendChild(el("span", "ledger__title", p.title));
    if (p.summary) main.appendChild(el("span", "ledger__summary", p.summary));
    b.appendChild(main);

    b.appendChild(el("span", "ledger__kind", kindOf(p)[0]));
    b.appendChild(el("span", "ledger__stack", (p.tags || []).slice(0, 4).join(", ")));
    b.appendChild(el("span", "ledger__date", p.date || ""));
    var go = el("span", "ledger__go");
    go.appendChild(icon("arrow"));
    b.appendChild(go);

    b.addEventListener("click", function () { openSheet(p); });
    li.appendChild(b);
    return li;
  }

  function renderLedger() {
    if (!others.length) { $("#more").hidden = true; return; }
    var list = $("#ledger");
    others.forEach(function (p, i) { list.appendChild(ledgerRow(p, featured.length + i + 1)); });

    /* Filters, one per type, only when there is more than one type. */
    var box = $("#filters"), groups = [], counts = {};
    others.forEach(function (p) {
      var g = kindOf(p)[1];
      if (!counts[g]) { counts[g] = 0; groups.push(g); }
      counts[g] += 1;
    });
    if (groups.length < 2) { box.hidden = true; return; }

    [["All", others.length]].concat(groups.map(function (g) { return [g, counts[g]]; }))
      .forEach(function (pair, i) {
        var b = el("button", "filter", pair[0]);
        b.type = "button";
        b.appendChild(el("sup", null, String(pair[1])));
        b.setAttribute("aria-label", pair[0] + ", " + pair[1]);
        b.setAttribute("aria-pressed", String(i === 0));
        b.addEventListener("click", function () {
          each(box.children, function (c) { c.setAttribute("aria-pressed", String(c === b)); });
          var shown = 0;
          each(list.children, function (row) {
            var hit = i === 0 || row.getAttribute("data-group") === pair[0];
            row.hidden = !hit;
            if (hit) shown += 1;
          });
          $("#ledger-empty").hidden = shown > 0;
        });
        box.appendChild(b);
      });
  }

  /* ============================================================ approach */
  function renderApproach() {
    var title = [approach.lead, approach.accent].filter(Boolean).join(" ");
    if (!title && !approach.statement && !toolkit.length) { $("#approach").hidden = true; return; }
    setText("#approach-title", title || "Approach");
    setText("#approach-statement", approach.statement || "");

    var bits = [];
    if (profile.focus) bits.push(["Current focus: ", profile.focus]);
    if (profile.location) bits.push(["Based in ", profile.location]);
    if (bits.length) {
      var f = $("#approach-focus");
      bits.forEach(function (b, i) {
        if (i) f.appendChild(document.createTextNode(". "));
        f.appendChild(el("b", null, b[0]));
        f.appendChild(document.createTextNode(b[1]));
      });
      f.hidden = false;
    }

    var box = $("#toolkit");
    if (!toolkit.length) { box.hidden = true; return; }
    var buckets = TOOL_GROUPS.map(function () { return []; });
    toolkit.forEach(function (t) {
      for (var i = 0; i < TOOL_GROUPS.length; i++) {
        if (TOOL_GROUPS[i][1].test(t)) { buckets[i].push(t); return; }
      }
    });
    TOOL_GROUPS.forEach(function (g, i) {
      if (!buckets[i].length) return;
      var col = el("div", "toolkit__group");
      col.appendChild(el("h3", null, g[0]));
      var ul = el("ul");
      buckets[i].forEach(function (t) { ul.appendChild(el("li", null, t)); });
      col.appendChild(ul);
      box.appendChild(col);
    });
  }

  /* ============================================================= contact */
  function renderContact() {
    var name = profile.name || "";
    var mail = profile.email || "";
    var link = $("#mail-link"), copy = $("#copy-mail");
    if (mail) {
      link.href = "mailto:" + mail;
      setText("#mail-text", mail);
      copy.addEventListener("click", function () {
        var done = function () {
          copy.textContent = "Copied to the clipboard";
          setTimeout(function () { copy.textContent = "Copy address"; }, 2000);
        };
        if (navigator.clipboard) navigator.clipboard.writeText(mail).then(done, done);
        else done();
      });
    } else {
      link.hidden = true;
      copy.hidden = true;
    }

    var box = $("#contact-links");
    [["LinkedIn", profile.linkedin], ["GitHub", profile.github], ["Résumé (PDF)", profile.resume]]
      .forEach(function (pair) {
        if (!pair[1]) return;
        var a = el("a", null, pair[0]);
        a.href = pair[1];
        a.target = "_blank";
        a.rel = "noopener";
        a.appendChild(icon("out"));
        box.appendChild(a);
      });
    if (!box.children.length) box.hidden = true;

    setText("#copyright", "© " + new Date().getFullYear() + " " + name);
  }

  /* ========================================================= the sheet */
  var sheet = $("#sheet"), sheetBody = $("#sheet-body"), sheetScroll = $("#sheet-scroll");
  var current = -1, returnFocus = null;

  function block(title) {
    var d = el("section", "block");
    d.appendChild(el("h3", null, title));
    return d;
  }

  function fact(dl, term, value, wide) {
    var d = el("div", wide ? "wide" : null);
    d.appendChild(el("dt", null, term));
    d.appendChild(el("dd", null, value));
    dl.appendChild(d);
  }

  function withheld(rec) {
    var box = el("div", "withheld");
    var ghost = el("pre", "withheld__ghost");
    ghost.setAttribute("aria-hidden", "true");
    ghost.textContent = rec.filler || "";
    box.appendChild(ghost);

    var face = el("div", "withheld__face");
    face.appendChild(el("span", "withheld__title", "Withheld"));
    face.appendChild(el("span", "withheld__line",
      nfmt(rec.hiddenLines) + " more line" + (rec.hiddenLines === 1 ? " is" : "s are") + " not published."));
    if (profile.email) {
      var ask = el("a", "withheld__ask", "Ask for the full source");
      ask.href = "mailto:" + profile.email + "?subject=" +
        encodeURIComponent("Source request: " + (rec.name || ""));
      face.appendChild(ask);
    }
    box.appendChild(face);
    return box;
  }

  function codePanel(path, rec) {
    var wrap = el("div", "code");
    var head = el("div", "code__head");
    head.appendChild(el("span", "code__name", rec.name || fileName(path)));
    head.appendChild(el("span", "code__lines", rec.locked
      ? "Lines " + rec.shownFrom + "–" + rec.shownTo + " of " + nfmt(rec.totalLines)
      : nfmt(rec.totalLines) + " lines"));
    if (rec.locked) head.appendChild(el("span", "tag", "Excerpt"));
    wrap.appendChild(head);

    var pre = el("pre", rec.locked ? "clipped" : null);
    pre.innerHTML = rec.lang === "markdown" ? tintMarkdown(rec.preview || "") : highlight(rec.preview || "");
    wrap.appendChild(pre);
    if (rec.locked) wrap.appendChild(withheld(rec));
    return wrap;
  }

  function pagerButton(p, label) {
    var b = el("button");
    b.type = "button";
    if (!p) { b.disabled = true; return b; }
    b.appendChild(el("small", null, label));
    b.appendChild(el("span", null, p.title));
    b.addEventListener("click", function () { openSheet(p); });
    return b;
  }

  function fillSheet(p) {
    sheetBody.innerHTML = "";
    var total = ordered.length;
    setText("#sheet-crumb", "Project " + pad2(current + 1) + " of " + pad2(total));
    $("#sheet-prev").disabled = current <= 0;
    $("#sheet-next").disabled = current >= total - 1;

    var kind = kindOf(p)[0];
    sheetBody.appendChild(el("p", "sheet__kicker", [kind, p.date].filter(Boolean).join(" · ")));
    var title = el("h2", "sheet__title", p.title);
    title.id = "sheet-title";
    sheetBody.appendChild(title);
    if (p.summary) sheetBody.appendChild(el("p", "sheet__summary", p.summary));

    var facts = el("dl", "facts");
    fact(facts, "Type", kind);
    if (p.date) fact(facts, "Date", p.date);
    var lc = lineCounts(p);
    if (lc.total) fact(facts, "Source", nfmt(lc.total) + " lines");
    if (p.tags && p.tags.length) fact(facts, isDocument(p) ? "Topics" : "Built with", p.tags.join(", "), true);
    if (p.note) fact(facts, "Note", p.note, true);
    sheetBody.appendChild(facts);

    var links = [];
    if (p.demo) links.push({ label: "Open the live build", url: p.demo });
    (p.links || []).forEach(function (l) { if (l && l.url) links.push(l); });
    if (links.length) {
      var row = el("div", "sheet__actions");
      links.forEach(function (l) { row.appendChild(outLink(l.url, l.label || l.url)); });
      sheetBody.appendChild(row);
    }

    var desc = (p.description || "").trim();
    if (desc) {
      var about = block(isDocument(p) ? "About the paper" : "About the project");
      var prose = el("div", "prose");
      desc.split(/\n\s*\n/).forEach(function (para) { prose.appendChild(el("p", null, para.trim())); });
      about.appendChild(prose);
      sheetBody.appendChild(about);
    }

    if (p.highlights && p.highlights.length) {
      var inside = block("What is inside");
      var ul = el("ul", "points");
      p.highlights.forEach(function (h) { ul.appendChild(el("li", null, h)); });
      inside.appendChild(ul);
      sheetBody.appendChild(inside);
    }

    if (p.metrics && p.metrics.length) {
      var nums = block("By the numbers");
      nums.appendChild(metricsList(p.metrics));
      sheetBody.appendChild(nums);
    }

    var images = imagesOf(p);
    if (images.length) {
      var doc = isDocument(p);
      var gal = block(doc ? "Pages" : images.length === 1 ? "Screenshot" : "Screenshots");
      var grid = el("div", "gallery" + (doc ? " gallery--pages" : ""));
      images.forEach(function (src) {
        var cap = captionFor(src, p);
        var fig = el("figure");
        var btn = el("button", "plate");
        btn.type = "button";
        btn.setAttribute("aria-label", "Enlarge " + cap.toLowerCase());
        var frame = el("div", "plate__frame");
        frame.appendChild(img(src, p.title + ", " + cap.toLowerCase()));
        btn.appendChild(frame);
        btn.addEventListener("click", function () { openLightbox(src, cap + ", " + p.title); });
        fig.appendChild(btn);
        fig.appendChild(el("figcaption", "plate-cap", cap));
        grid.appendChild(fig);
      });
      gal.appendChild(grid);
      sheetBody.appendChild(gal);
    }

    (p.docs || []).forEach(function (src, i) {
      var read = block(i === 0 ? "Read it here" : fileName(src));
      read.appendChild(el("p", "note", "Shown in the page. There is no download."));
      var frame = document.createElement("iframe");
      frame.className = "pdf";
      frame.src = encodeURI(src) + "#toolbar=0&navpanes=0";   // hides the viewer's own save button
      frame.title = fileName(src);
      frame.loading = "lazy";
      read.appendChild(frame);
      sheetBody.appendChild(read);
    });

    var panels = (p.code || []).map(function (c) {
      var path = codePath(c), rec = PREVIEWS[path];
      return rec && !rec.manifestOnly ? codePanel(path, rec) : null;
    }).filter(Boolean);
    if (panels.length) {
      var src = block(panels.length === 1 ? "Source" : "Source files");
      panels.forEach(function (panel) { src.appendChild(panel); });
      sheetBody.appendChild(src);
    }

    var man = MANIFESTS[p.id];
    if (man && man.files && man.files.length) {
      var pkg = block("Package contents");
      pkg.appendChild(el("p", "note", man.lockedFiles
        ? nfmt(man.totalFiles) + " further module" + (man.totalFiles === 1 ? "" : "s") + ", " +
          nfmt(man.totalLines) + " lines. Listed for scale, not published."
        : nfmt(man.totalFiles) + " further file" + (man.totalFiles === 1 ? "" : "s") + ", " +
          nfmt(man.totalLines) + " lines."));
      var files = el("div", "files");
      man.files.forEach(function (f) {
        var r = el("div");
        r.appendChild(el("span", "f-name", f.name));
        r.appendChild(el("span", "f-lines", nfmt(f.lines) + " lines"));
        if (f.locked) r.appendChild(el("span", "f-lock", "Withheld"));
        files.appendChild(r);
      });
      pkg.appendChild(files);
      sheetBody.appendChild(pkg);
    }

    var pager = el("nav", "pager");
    pager.setAttribute("aria-label", "Other projects");
    pager.appendChild(pagerButton(ordered[current - 1], "Previous"));
    pager.appendChild(pagerButton(ordered[current + 1], "Next"));
    sheetBody.appendChild(pager);
  }

  function openSheet(p) {
    if (!sheet.open) returnFocus = document.activeElement;
    current = ordered.indexOf(p);
    fillSheet(p);
    if (!sheet.open) {
      if (typeof sheet.showModal === "function") sheet.showModal();
      else sheet.setAttribute("open", "");
    }
    sheetScroll.scrollTop = 0;
    $("#sheet-close").focus();
    if (p.id && history.replaceState) history.replaceState(null, "", "#" + p.id);
  }

  function closeSheet() {
    if (typeof sheet.close === "function") sheet.close();
    else sheet.removeAttribute("open");
    onSheetClosed();
  }

  /* Runs from the close button and from the dialog's own close event (Escape),
     whichever comes first. */
  function onSheetClosed() {
    if (current === -1) return;
    current = -1;
    sheetBody.innerHTML = "";          // also unloads any PDF viewer
    if (history.replaceState) history.replaceState(null, "", location.pathname + location.search);
    if (returnFocus && returnFocus.focus) returnFocus.focus();
  }

  sheet.addEventListener("close", onSheetClosed);
  $("#sheet-close").addEventListener("click", closeSheet);
  $("#sheet-prev").addEventListener("click", function () { if (current > 0) openSheet(ordered[current - 1]); });
  $("#sheet-next").addEventListener("click", function () {
    if (current < ordered.length - 1) openSheet(ordered[current + 1]);
  });
  /* a click on the dimmed page beside the sheet closes it */
  sheet.addEventListener("click", function (e) {
    if (e.target === sheet && e.clientX < sheet.getBoundingClientRect().left) closeSheet();
  });

  /* ============================================================ lightbox */
  var lightbox = $("#lightbox");
  function openLightbox(src, caption) {
    var im = $("#lightbox-img");
    im.src = src;
    im.alt = caption;
    setText("#lightbox-cap", caption);
    if (typeof lightbox.showModal === "function") lightbox.showModal();
    else lightbox.setAttribute("open", "");
    $("#lightbox-close").focus();
  }
  lightbox.addEventListener("click", function () {
    if (typeof lightbox.close === "function") lightbox.close();
    else lightbox.removeAttribute("open");
  });
  lightbox.addEventListener("close", function () { $("#lightbox-img").removeAttribute("src"); });

  /* ================================================= Fig. 1, the fan chart */
  /* One year of a $100 stock under geometric Brownian motion, simulated
     10,000 times with a seeded generator, so the figure is the same on every
     load until someone asks for a new sample. */
  function fanChart(fig) {
    var canvas = fig.querySelector("canvas");
    var ctx = canvas.getContext && canvas.getContext("2d");
    if (!ctx) { fig.hidden = true; return; }
    var button = fig.querySelector(".fan__rerun");

    var N = 10000, STEPS = 126, DT = 2 / 252;        // two trading days a step
    var S0 = 100, MU = 0.08, SIGMA = 0.22;
    var DRAWN = 110, BINS = 34;
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var state = null, seed = 1907, reveal = 1, frame = 0, palette = null;

    function generator(a) {                          // mulberry32
      return function () {
        a = (a + 0x6d2b79f5) | 0;
        var t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    }

    function quantile(sorted, p) {
      var i = (sorted.length - 1) * p, lo = Math.floor(i), hi = Math.min(lo + 1, sorted.length - 1);
      return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
    }

    /* Runs in small slices so the page never stalls while it computes. */
    function simulate(s, done) {
      var rand = generator(s), spare = null;
      function normal() {                            // Box-Muller, both values used
        if (spare !== null) { var z = spare; spare = null; return z; }
        var u = 0;
        while (u === 0) u = rand();
        var r = Math.sqrt(-2 * Math.log(u)), th = 2 * Math.PI * rand();
        spare = r * Math.sin(th);
        return r * Math.cos(th);
      }
      var drift = (MU - SIGMA * SIGMA / 2) * DT, vol = SIGMA * Math.sqrt(DT);
      var cols = [], drawn = [], i = 0, k;
      for (k = 0; k <= STEPS; k++) cols.push(new Float32Array(N));

      function paths() {
        var end = Math.min(N, i + 1250);
        for (; i < end; i++) {
          var x = S0, keep = i < DRAWN ? new Float32Array(STEPS + 1) : null;
          cols[0][i] = x;
          if (keep) keep[0] = x;
          for (k = 1; k <= STEPS; k++) {
            x *= Math.exp(drift + vol * normal());
            cols[k][i] = x;
            if (keep) keep[k] = x;
          }
          if (keep) drawn.push(keep);
        }
        if (i < N) setTimeout(paths, 0);
        else { k = 0; setTimeout(sortColumns, 0); }
      }

      var bands = { p5: [], p25: [], p50: [], p75: [], p95: [] };
      function sortColumns() {
        var stop = Math.min(STEPS + 1, k + 32);
        for (; k < stop; k++) {
          var c = cols[k];
          c.sort();
          bands.p5.push(quantile(c, .05));
          bands.p25.push(quantile(c, .25));
          bands.p50.push(quantile(c, .5));
          bands.p75.push(quantile(c, .75));
          bands.p95.push(quantile(c, .95));
        }
        if (k <= STEPS) { setTimeout(sortColumns, 0); return; }

        var last = cols[STEPS];
        var lo = Math.min(quantile(last, .006), S0) * .93;
        var hi = quantile(last, .994) * 1.03;
        var hist = [], below = 0, b;
        for (b = 0; b < BINS; b++) hist.push(0);
        for (i = 0; i < N; i++) {
          b = Math.floor((last[i] - lo) / (hi - lo) * BINS);
          if (b >= 0 && b < BINS) hist[b] += 1;
          if (last[i] < S0) below += 1;
        }
        done({
          drawn: drawn, bands: bands, lo: lo, hi: hi, hist: hist,
          p5: quantile(last, .05), p50: quantile(last, .5), p95: quantile(last, .95),
          below: below / N
        });
      }
      paths();
    }

    function readPalette() {
      var cs = getComputedStyle(document.documentElement);
      var pick = function (name) { return cs.getPropertyValue(name).trim().split(/\s+/).join(","); };
      return { light: pick("--light-rgb"), accent: pick("--accent-rgb") };
    }
    function rgba(rgb, a) { return "rgba(" + rgb + "," + a + ")"; }
    function niceStep(range) {
      var steps = [5, 10, 20, 25, 50, 100, 200];
      for (var i = 0; i < steps.length; i++) if (range / steps[i] <= 7) return steps[i];
      return 500;
    }
    function easeOut(t) { t = Math.max(0, Math.min(1, t)); return 1 - Math.pow(1 - t, 3); }

    function draw() {
      if (!state) return;
      var w = canvas.clientWidth, h = canvas.clientHeight;
      if (!w || !h) return;
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var cw = Math.round(w * dpr), ch = Math.round(h * dpr);
      if (canvas.width !== cw || canvas.height !== ch) { canvas.width = cw; canvas.height = ch; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      var C = palette || (palette = readPalette());

      var fs = Math.max(10.5, Math.min(12.5, w / 44));
      var labelW = fs * 5.6;
      var top = fs * .8, bottom = h - fs * 2.6, plotH = bottom - top;
      var left = 0, right = (w - labelW) * .79;
      var histL = right + fs * 1.2, histR = w - labelW - fs * .6;
      var X = function (k) { return left + (right - left) * k / STEPS; };
      var Y = function (v) { return top + plotH * (1 - (v - state.lo) / (state.hi - state.lo)); };
      var sans = "'Libre Franklin', 'Helvetica Neue', Arial, sans-serif";

      var shown = easeOut(reveal / .8);              // paths draw across the first 80%
      var grow = easeOut((reveal - .6) / .4);        // the histogram rises over the last 40%

      /* grid */
      var step = niceStep(state.hi - state.lo), v, y;
      ctx.font = "400 " + (fs * .92) + "px " + sans;
      ctx.textBaseline = "bottom";
      ctx.textAlign = "left";
      for (v = Math.ceil(state.lo / step) * step; v < state.hi; v += step) {
        if (Math.abs(v - S0) < step / 2) continue;
        y = Math.round(Y(v)) + .5;
        ctx.fillStyle = rgba(C.light, .07);
        ctx.fillRect(left, y, histR - left, 1);
        ctx.fillStyle = rgba(C.light, .42);
        ctx.fillText(String(v), left + 2, y - 4);
      }

      /* the starting price */
      y = Math.round(Y(S0)) + .5;
      ctx.strokeStyle = rgba(C.light, .34);
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 4]);
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(histR, y);
      ctx.stroke();
      ctx.setLineDash([]);

      /* paths and percentile bands, revealed left to right */
      ctx.save();
      ctx.beginPath();
      ctx.rect(left, 0, (right - left) * shown + 1, bottom);
      ctx.clip();

      ctx.strokeStyle = rgba(C.light, .1);
      ctx.lineWidth = 1;
      ctx.lineJoin = "round";
      state.drawn.forEach(function (path) {
        ctx.beginPath();
        ctx.moveTo(X(0), Y(path[0]));
        for (var k = 1; k <= STEPS; k++) ctx.lineTo(X(k), Y(path[k]));
        ctx.stroke();
      });

      function band(a, b, fill) {
        ctx.beginPath();
        ctx.moveTo(X(0), Y(a[0]));
        for (var k = 1; k <= STEPS; k++) ctx.lineTo(X(k), Y(a[k]));
        for (k = STEPS; k >= 0; k--) ctx.lineTo(X(k), Y(b[k]));
        ctx.closePath();
        ctx.fillStyle = fill;
        ctx.fill();
      }
      function line(a, stroke, width) {
        ctx.beginPath();
        ctx.moveTo(X(0), Y(a[0]));
        for (var k = 1; k <= STEPS; k++) ctx.lineTo(X(k), Y(a[k]));
        ctx.strokeStyle = stroke;
        ctx.lineWidth = width;
        ctx.stroke();
      }
      band(state.bands.p5, state.bands.p95, rgba(C.accent, .12));
      band(state.bands.p25, state.bands.p75, rgba(C.accent, .17));
      line(state.bands.p95, rgba(C.accent, .62), 1);
      line(state.bands.p5, rgba(C.accent, .62), 1);
      line(state.bands.p50, rgba(C.accent, 1), 1.7);
      ctx.restore();

      ctx.fillStyle = rgba(C.accent, 1);
      ctx.beginPath();
      ctx.arc(X(0) + 3, Y(S0), 3.2, 0, Math.PI * 2);
      ctx.fill();

      /* where the paths finish */
      if (grow > 0) {
        var max = Math.max.apply(null, state.hist);
        var binH = plotH / BINS;
        ctx.fillStyle = rgba(C.accent, .85);
        for (var b = 0; b < BINS; b++) {
          var len = (histR - histL) * state.hist[b] / max * grow;
          if (len < .5) continue;
          var y0 = Y(state.lo + (b + 1) * (state.hi - state.lo) / BINS);
          ctx.fillRect(histL, y0 + .75, len, Math.max(1, binH - 1.5));
        }
        ctx.fillStyle = rgba(C.light, .3);
        ctx.fillRect(histL - 1, top, 1, plotH);

        ctx.globalAlpha = grow;
        [[state.p95, "95th pct."], [state.p50, "Median"], [state.p5, "5th pct."]].forEach(function (row) {
          var ly = Y(row[0]);
          ctx.fillStyle = rgba(C.light, .35);
          ctx.fillRect(histR + fs * .2, Math.round(ly), fs * .5, 1);
          ctx.textAlign = "left";
          ctx.textBaseline = "alphabetic";
          ctx.fillStyle = rgba(C.light, .95);
          ctx.font = "500 " + (fs * 1.08) + "px " + sans;
          ctx.fillText("$" + Math.round(row[0]), histR + fs * 1, ly + fs * .36);
          ctx.fillStyle = rgba(C.light, .58);
          ctx.font = "400 " + (fs * .86) + "px " + sans;
          ctx.fillText(row[1], histR + fs * 1, ly + fs * 1.6);
        });
        ctx.globalAlpha = 1;
      }

      /* time axis */
      ctx.fillStyle = rgba(C.light, .26);
      ctx.fillRect(left, Math.round(bottom) + .5, right - left, 1);
      ctx.font = "400 " + (fs * .92) + "px " + sans;
      ctx.textBaseline = "top";
      ["Today", "3 mo", "6 mo", "9 mo", "1 yr"].forEach(function (label, i) {
        var x = X(STEPS * i / 4);
        ctx.fillStyle = rgba(C.light, .3);
        ctx.fillRect(Math.round(x) - (i === 4 ? 1 : 0), Math.round(bottom), 1, 5);
        ctx.fillStyle = rgba(C.light, .58);
        ctx.textAlign = i === 0 ? "left" : i === 4 ? "right" : "center";
        ctx.fillText(label, x, bottom + fs * .75);
      });
    }

    function play() {
      cancelAnimationFrame(frame);
      if (reduce) { reveal = 1; draw(); return; }
      var start = null;
      reveal = 0;
      frame = requestAnimationFrame(function tick(ts) {
        if (start === null) start = ts;
        reveal = Math.min(1, (ts - start) / 2400);
        draw();
        if (reveal < 1) frame = requestAnimationFrame(tick);
      });
    }

    function run() {
      button.disabled = true;
      simulate(seed, function (result) {
        state = result;
        button.disabled = false;
        setText("#fan-summary", "Simulated result: a median year-end price of $" + Math.round(result.p50) +
          ", a 5th percentile of $" + Math.round(result.p5) + " and a 95th percentile of $" +
          Math.round(result.p95) + ". " + Math.round(result.below * 100) + "% of paths finish below $100.");
        play();
      });
    }

    button.addEventListener("click", function () {
      seed = (seed * 48271) % 2147483647;
      run();
    });
    if (window.ResizeObserver) new ResizeObserver(function () { draw(); }).observe(canvas.parentNode);
    else window.addEventListener("resize", draw);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { draw(); });
    run();
  }

  /* ================================================================ start */
  renderHero();
  renderPrinciples();
  renderWork();
  renderLedger();
  renderApproach();
  renderContact();
  fanChart($("#fan"));

  if (location.hash) {
    var want = decodeURIComponent(location.hash.slice(1));
    var hit = ordered.filter(function (p) { return p.id === want; })[0];
    if (hit) openSheet(hit);
  }
})();
