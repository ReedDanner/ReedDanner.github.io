/* Portfolio front-end. No dependencies, no build step.
   Reads window.PORTFOLIO from data/portfolio.js */
(function () {
  "use strict";

  var DATA = window.PORTFOLIO || {};
  /* Source excerpts are baked in by tools/protect.py. The full files are not
     on the site at all, so there is nothing here to fetch or unblur. */
  var PREVIEWS = window.PORTFOLIO_PREVIEWS || {};
  var MANIFESTS = window.PORTFOLIO_MANIFESTS || {};
  var profile = DATA.profile || {};
  var approach = DATA.approach || {};
  var toolkit = DATA.toolkit || [];
  var projects = (DATA.projects || []).slice();

  var KIND_LABEL = {
    app: "Application", code: "Code", website: "Website", algorithm: "Algorithm",
    research: "Research", document: "Document", design: "Design", data: "Data",
    other: "Project"
  };

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var el = function (tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  var setText = function (sel, txt) {
    var n = $(sel);
    if (n) n.textContent = txt || "";
  };

  function initials(name) {
    var words = (name || "?").split(/[\s\-_/]+/).filter(function (w) {
      return /^[A-Za-z0-9]/.test(w);
    });
    if (!words.length) return "?";
    return words.slice(0, 2).map(function (w) { return w[0].toUpperCase(); }).join("");
  }

  /* ------------------------------------------------ page chrome ---- */
  function renderProfile() {
    var name = profile.name || "Portfolio";
    document.title = name + (profile.kicker ? " - " + profile.kicker : "");

    setText("#mark", profile.monogram || initials(name));
    setText("#brand-name", name);
    setText("#hero-status", profile.status || "");
    setText("#hero-kicker", (name + " / " + (profile.kicker || "")).replace(/ \/ $/, ""));
    setText("#head-lead", (profile.headline && profile.headline.lead) || name);
    setText("#head-accent", (profile.headline && profile.headline.accent) || "");
    setText("#hero-intro", profile.intro || "");
    setText("#hero-focus", profile.focus || "");
    setText("#hero-place", profile.location || "");
    setText("#foot-left", "© " + new Date().getFullYear() + " " + name);

    if (!profile.status) {
      var eb = $(".eyebrow");
      if (eb) eb.hidden = true;
    }

    var gh = profile.github || "";
    var li = profile.linkedin || "";
    [["#gh-top", gh], ["#gh-foot", gh], ["#li-foot", li]].forEach(function (pair) {
      var node = $(pair[0]);
      if (!node) return;
      if (pair[1]) { node.href = pair[1]; node.hidden = false; }
    });

    var mail = profile.email || "";
    var mailLink = $("#mail-link");
    if (mail) {
      mailLink.href = "mailto:" + mail;
      setText("#mail-text", mail);
      $("#copy-mail").addEventListener("click", function () {
        var btn = $("#copy-mail");
        var done = function () {
          btn.textContent = "Copied";
          setTimeout(function () { btn.textContent = "Copy email"; }, 1800);
        };
        if (navigator.clipboard) navigator.clipboard.writeText(mail).then(done, done);
        else done();
      });
    } else {
      mailLink.hidden = true;
      $("#copy-mail").hidden = true;
    }
  }

  function renderApproach() {
    var sec = $("#approach");
    if (!approach.statement && !(approach.points || []).length) {
      if (sec) sec.hidden = true;
      return;
    }
    setText("#ap-lead", approach.lead || "How I");
    setText("#ap-accent", approach.accent || "work.");
    setText("#ap-statement", approach.statement || "");
    if (profile.location) {
      var pl = $("#place-label");
      pl.textContent = "Based in " + profile.location;
      pl.className = "mono dim tiny place-line";
    }

    var list = $("#points");
    (approach.points || []).forEach(function (pt, i) {
      var li = document.createElement("li");
      li.appendChild(el("span", "n", "0" + (i + 1)));
      var txt = el("div", "txt");
      txt.appendChild(el("h3", null, pt.title));
      txt.appendChild(el("p", null, pt.body));
      li.appendChild(txt);
      list.appendChild(li);
    });
  }

  function renderToolkit() {
    var sec = $("#toolkit");
    if (!toolkit.length) { if (sec) sec.hidden = true; return; }
    var list = $("#tools");
    toolkit.forEach(function (t) { list.appendChild(el("li", null, t)); });
  }

  /* ------------------------------------------------ project cards ---- */
  function card(p) {
    var b = el("button", "wcard");
    b.type = "button";
    b.setAttribute("aria-label", "Open " + p.title);

    var shot = el("div", "wshot");
    if (p.cover) {
      var im = new Image();
      im.src = p.cover; im.alt = ""; im.loading = "lazy";
      im.onerror = function () {         // missing file: fall back, keep the overlay
        im.remove();
        shot.classList.add("gen");
        shot.insertBefore(el("span", "init", initials(p.title)), shot.firstChild);
      };
      shot.appendChild(im);
    } else {
      shot.classList.add("gen");
      shot.appendChild(el("span", "init", initials(p.title)));
    }
    shot.appendChild(el("span", "go", "↗"));
    b.appendChild(shot);

    var meta = el("div", "wmeta");
    meta.appendChild(el("span", null, KIND_LABEL[p.kind] || KIND_LABEL.other));
    if (p.date) meta.appendChild(el("span", null, p.date));
    b.appendChild(meta);

    var body = el("div", "wbody");
    body.appendChild(el("h3", null, p.title));
    body.appendChild(el("p", null, p.summary || ""));
    if (p.tags && p.tags.length) {
      var tw = el("div", "wtags");
      p.tags.slice(0, 5).forEach(function (t) { tw.appendChild(el("span", "wtag", t)); });
      body.appendChild(tw);
    }
    b.appendChild(body);

    b.addEventListener("click", function () { openModal(p); });
    return b;
  }

  /* ------------------------------------------------ filtering ---- */
  var state = { q: "", kind: "all" };

  function matches(p) {
    if (state.kind !== "all" && p.kind !== state.kind) return false;
    if (!state.q) return true;
    var hay = [p.title, p.summary, p.description, (p.tags || []).join(" "), p.kind]
      .join(" ").toLowerCase();
    return state.q.split(/\s+/).every(function (w) { return hay.indexOf(w) > -1; });
  }

  function ordered() {
    var feat = projects.filter(function (p) { return p.featured; });
    var rest = projects.filter(function (p) { return !p.featured; });
    return feat.concat(rest);
  }

  function render() {
    var list = ordered().filter(matches);
    var grid = $("#grid");
    grid.innerHTML = "";
    list.forEach(function (p) { grid.appendChild(card(p)); });
    $("#empty").hidden = list.length > 0 || !projects.length;
    $("#getting-started").hidden = projects.length > 0;
  }

  function buildFilters() {
    var kinds = [];
    projects.forEach(function (p) {
      if (p.kind && kinds.indexOf(p.kind) === -1) kinds.push(p.kind);
    });
    var box = $("#filters");
    if (kinds.length < 2) { box.hidden = true; return; }
    ["all"].concat(kinds).forEach(function (k) {
      var b = el("button", "chip", k === "all" ? "All" : (KIND_LABEL[k] || k));
      b.type = "button";
      b.setAttribute("aria-pressed", String(k === "all"));
      b.addEventListener("click", function () {
        state.kind = k;
        Array.prototype.forEach.call(box.children, function (c) {
          c.setAttribute("aria-pressed", String(c === b));
        });
        render();
      });
      box.appendChild(b);
    });
  }

  /* ------------------------------------------------ code highlight ---- */
  var KW = ("abstract as assert async await base bool break case catch char class const continue " +
    "def default del elif else except export extends final finally float for from func function " +
    "global go if implements import in int interface is lambda let match new nil none not null or " +
    "package pass private protected public raise return self static struct super switch this throw " +
    "true false try type typeof using var void while with yield and enum event fn impl mod pub " +
    "trait unsafe where").split(" ");
  var KWSET = {};
  KW.forEach(function (k) { KWSET[k] = 1; });

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function highlight(src) {
    var out = "";
    var re = /(\/\*[\s\S]*?\*\/|(?:^|\s)#[^\n]*|\/\/[^\n]*|<!--[\s\S]*?-->)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)|(\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|([A-Za-z_$][\w$]*)/g;
    var last = 0, m;
    while ((m = re.exec(src)) !== null) {
      out += esc(src.slice(last, m.index));
      last = re.lastIndex;
      if (m[1]) out += '<span class="tok-com">' + esc(m[1]) + "</span>";
      else if (m[2]) out += '<span class="tok-str">' + esc(m[2]) + "</span>";
      else if (m[3]) out += '<span class="tok-num">' + esc(m[3]) + "</span>";
      else {
        var w = m[4];
        if (KWSET[w]) out += '<span class="tok-kw">' + esc(w) + "</span>";
        else if (src[re.lastIndex] === "(") out += '<span class="tok-fn">' + esc(w) + "</span>";
        else out += esc(w);
      }
    }
    return out + esc(src.slice(last));
  }

  /* ------------------------------------------------ modal ---- */
  var modal = $("#modal"), modalBody = $("#modal-body"), lastFocus = null;

  function block(title) {
    var d = el("div", "m-block");
    d.appendChild(el("h4", null, title));
    return d;
  }
  function fileName(path) { return String(path).split("/").pop(); }
  function nfmt(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }

  /* ------------------------------------------------ gated source ---- */
  function lockPanel(rec) {
    var lock = el("div", "codelock");

    var ghost = el("pre", "ghost");
    ghost.setAttribute("aria-hidden", "true");
    ghost.textContent = rec.filler || "";
    lock.appendChild(ghost);

    var face = el("div", "lockface");
    face.appendChild(el("span", "lockmark", "Withheld"));
    face.appendChild(el("p", "lockline",
      nfmt(rec.hiddenLines) + " more line" + (rec.hiddenLines === 1 ? "" : "s") +
      " are not published."));
    if (profile.email) {
      var ask = el("a", "btn sm", "Request full source");
      ask.href = "mailto:" + profile.email + "?subject=" +
        encodeURIComponent("Source request: " + (rec.name || ""));
      face.appendChild(ask);
    }
    lock.appendChild(face);
    return lock;
  }

  function codePanel(path, rec) {
    var wrap = el("div", "codewrap");

    var head = el("div", "codehead");
    head.appendChild(el("span", "grow", rec.name || fileName(path)));
    head.appendChild(el("span", "linecount", rec.locked
      ? "lines " + rec.shownFrom + "-" + rec.shownTo + " of " + nfmt(rec.totalLines)
      : nfmt(rec.totalLines) + " lines"));
    if (rec.locked) head.appendChild(el("span", "pill", "Locked"));
    wrap.appendChild(head);

    var pre = el("pre", rec.locked ? "clipped" : null);
    pre.innerHTML = highlight(rec.preview || "");
    wrap.appendChild(pre);

    if (rec.locked) wrap.appendChild(lockPanel(rec));
    return wrap;
  }

  function openModal(p) {
    lastFocus = document.activeElement;
    modalBody.innerHTML = "";
    modalBody.appendChild(el("h2", null, p.title));

    var bits = [KIND_LABEL[p.kind] || KIND_LABEL.other];
    if (p.date) bits.push(p.date);
    if (p.tags && p.tags.length) bits.push(p.tags.join(" / "));
    modalBody.appendChild(el("p", "m-sub", bits.join("  ·  ")));

    if (p.description || p.summary) {
      modalBody.appendChild(el("p", "m-desc", p.description || p.summary));
    }

    var linkRow = [];
    (p.links || []).forEach(function (lk) { if (lk && lk.url) linkRow.push(lk); });
    if (p.demo) linkRow.unshift({ label: "Open live version", url: p.demo });
    if (linkRow.length) {
      var lb = block("Links");
      var lw = el("div", "m-links");
      linkRow.forEach(function (lk) {
        var a = el("a", "btn", (lk.label || lk.url) + "  ↗");
        a.href = lk.url; a.target = "_blank"; a.rel = "noopener";
        lw.appendChild(a);
      });
      lb.appendChild(lw);
      modalBody.appendChild(lb);
    }

    if (p.images && p.images.length) {
      var gb = block(p.images.length === 1 ? "Screenshot" : "Screenshots");
      var g = el("div", "gallery");
      p.images.forEach(function (src) {
        var im = new Image();
        im.src = src; im.alt = p.title + " screenshot"; im.loading = "lazy";
        im.addEventListener("click", function () { openLightbox(src); });
        g.appendChild(im);
      });
      gb.appendChild(g);
      modalBody.appendChild(gb);
    }

    (p.docs || []).forEach(function (doc, i) {
      var db = block(i === 0 ? "Document" : fileName(doc));
      db.appendChild(el("p", "m-note", "Read here. No download."));
      var fr = document.createElement("iframe");
      fr.className = "pdfframe";
      fr.src = doc + "#toolbar=0&navpanes=0";   // hides the viewer's own save button
      fr.title = fileName(doc);
      db.appendChild(fr);
      modalBody.appendChild(db);
    });

    var panels = (p.code || []).map(function (c) {
      var path = typeof c === "string" ? c : c.path;
      var rec = PREVIEWS[path];
      return (rec && !rec.manifestOnly) ? codePanel(path, rec) : null;
    }).filter(Boolean);

    if (panels.length) {
      var cb = block(panels.length === 1 ? "Source" : "Source files");
      panels.forEach(function (panel) { cb.appendChild(panel); });
      modalBody.appendChild(cb);
    }

    var man = MANIFESTS[p.id];
    if (man && man.files && man.files.length) {
      var fb = block("Package contents");
      var note = man.lockedFiles
        ? nfmt(man.totalFiles) + " further module" + (man.totalFiles === 1 ? "" : "s") +
          ", " + nfmt(man.totalLines) + " lines. Listed for scale, not published."
        : nfmt(man.totalFiles) + " further file" + (man.totalFiles === 1 ? "" : "s") +
          ", " + nfmt(man.totalLines) + " lines.";
      fb.appendChild(el("p", "m-note", note));
      var fl = el("div", "filelist");
      man.files.forEach(function (f) {
        var row = el("div", "filerow");
        row.appendChild(el("span", "fname", f.name));
        row.appendChild(el("span", "fsize", nfmt(f.lines) + " lines"));
        if (f.locked) row.appendChild(el("span", "pill sm", "Locked"));
        fl.appendChild(row);
      });
      fb.appendChild(fl);
      modalBody.appendChild(fb);
    }

    modal.hidden = false;
    document.body.style.overflow = "hidden";
    $(".modal-close").focus();
    if (p.id && history.replaceState) history.replaceState(null, "", "#" + p.id);
  }

  function closeModal() {
    modal.hidden = true;
    modalBody.innerHTML = "";
    document.body.style.overflow = "";
    if (history.replaceState) history.replaceState(null, "", location.pathname + location.search);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  var lightbox = $("#lightbox");
  function openLightbox(src) { $("#lb-img").src = src; lightbox.hidden = false; }
  function closeLightbox() { lightbox.hidden = true; $("#lb-img").src = ""; }

  /* ------------------------------------------------ wire up ---- */
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-close]")) closeModal();
    if (e.target.closest(".lb-close") || e.target === lightbox) closeLightbox();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (!lightbox.hidden) closeLightbox();
    else if (!modal.hidden) closeModal();
  });

  var t;
  $("#search").addEventListener("input", function (e) {
    clearTimeout(t);
    var v = e.target.value.trim().toLowerCase();
    t = setTimeout(function () { state.q = v; render(); }, 110);
  });

  renderProfile();
  renderApproach();
  renderToolkit();
  buildFilters();
  render();

  if (location.hash) {
    var want = location.hash.slice(1);
    var hit = projects.filter(function (p) { return p.id === want; })[0];
    if (hit) openModal(hit);
  }
})();
