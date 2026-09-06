/* Favori "Token Midrag" — source lisible.
 *
 * Midrag n'autorise les appels à son API que depuis son propre domaine
 * (en-têtes CORS restreints à bizn.midrag.co.il): la page de configuration
 * ne peut donc pas faire la connexion elle-même. Ce code, lui, s'exécute
 * DANS la page Midrag, donc il a le droit d'appeler l'API — il rejoue la
 * connexion officielle (Account/Login -> Account/SendCode -> Account/Token,
 * exactement les trois appels du formulaire du site) et affiche le token
 * obtenu, prêt à coller dans la page de configuration.
 *
 * token.html transforme ce fichier en URL "javascript:" — ne pas le
 * dupliquer ailleurs.
 */
(async () => {
  const API = "https://biz-api.midrag.co.il/";
  const CREDS_KEY = "midrag_token_helper_creds";
  const CONFIG_PAGE = "https://rnab26.github.io/Midrag/";
  const OK = 1; // operationStatus.Success

  if (!/(^|\.)midrag\.co\.il$/.test(location.hostname)) {
    alert(
      "Ouvre d'abord bizn.midrag.co.il, puis relance ce favori depuis cette page.\n\n" +
      "(Midrag n'accepte ces appels que depuis son propre site.)"
    );
    return;
  }
  if (document.getElementById("midrag-token-helper")) return;

  const post = async (path, body) => {
    const res = await fetch(API + path, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    let json = null;
    try { json = await res.json(); } catch (e) { /* réponse non JSON */ }
    if (!json) throw new Error("Réponse illisible de Midrag (HTTP " + res.status + ").");
    if (json.operationStatus !== OK) {
      throw new Error(json.message || "Midrag a refusé la demande (code " + (json.errorCode ?? json.operationStatus) + ").");
    }
    // L'API renvoie {operationStatus, data}, et data est souvent un objet à
    // une seule clé ({uuid: ...}, {token: ...}) — on la déballe comme le
    // fait le site lui-même.
    let data = json.data;
    if (data && typeof data === "object" && !Array.isArray(data)) {
      const keys = Object.keys(data);
      if (keys.length === 1) data = data[keys[0]];
    }
    return data;
  };

  const expiryOf = (token) => {
    try {
      const part = token.split(".")[1];
      const b64 = part.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (part.length % 4)) % 4);
      const exp = JSON.parse(decodeURIComponent(escape(atob(b64)))).exp;
      return exp ? new Date(exp * 1000) : null;
    } catch (e) { return null; }
  };

  const el = (tag, style, props) => Object.assign(
    Object.assign(document.createElement(tag), props || {}),
    { style: style || "" }
  );

  const box = el("div", [
    "position:fixed", "inset:0", "z-index:2147483647", "background:rgba(0,0,0,.55)",
    "display:flex", "align-items:center", "justify-content:center", "padding:16px",
    "direction:ltr", "font:14px -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif",
  ].join(";"));
  box.id = "midrag-token-helper";
  const card = el("div", [
    "background:#fff", "color:#1c1c1e", "border-radius:14px", "padding:18px",
    "width:100%", "max-width:380px", "max-height:90vh", "overflow:auto",
    "box-shadow:0 10px 40px rgba(0,0,0,.3)",
  ].join(";"));
  box.appendChild(card);
  document.body.appendChild(box);

  const close = () => box.remove();
  box.addEventListener("click", (e) => { if (e.target === box) close(); });

  const H = (text) => el("div", "font-weight:700;font-size:16px;margin-bottom:12px", { textContent: text });
  const P = (text) => el("div", "color:#6e6e73;font-size:12px;margin:-6px 0 12px", { textContent: text });
  const L = (text) => el("label", "display:block;font-size:12px;color:#6e6e73;margin-bottom:4px", { textContent: text });
  const I = (value, ph, mode) => el("input", "width:100%;padding:10px;border:1px solid #dcdce0;border-radius:8px;font-size:16px;margin-bottom:10px;background:#fff;color:#1c1c1e", {
    value: value || "", placeholder: ph || "", inputMode: mode || "text", autocomplete: "off",
  });
  const B = (text, primary) => el("button", [
    "width:100%", "padding:12px", "border:none", "border-radius:10px", "font-size:15px",
    "font-weight:600", "cursor:pointer", "margin-bottom:8px",
    primary ? "background:#a3134f;color:#fff" : "background:#ececef;color:#1c1c1e",
  ].join(";"), { type: "button", textContent: text });
  const status = el("div", "font-size:13px;margin-top:6px;min-height:18px");
  const say = (text, kind) => {
    status.textContent = text || "";
    status.style.color = kind === "err" ? "#b3261e" : kind === "ok" ? "#1e7e34" : "#6e6e73";
  };

  let creds = {};
  try { creds = JSON.parse(localStorage.getItem(CREDS_KEY) || "{}"); } catch (e) { creds = {}; }

  const render = (view, data) => {
    card.textContent = "";
    const closeBtn = el("button", "float:right;border:none;background:none;font-size:20px;line-height:1;cursor:pointer;color:#6e6e73;padding:0 0 8px 8px", { type: "button", textContent: "✕" });
    closeBtn.addEventListener("click", close);
    card.appendChild(closeBtn);
    view(data);
    card.appendChild(status);
  };

  const loginView = () => {
    card.appendChild(H("🔑 Token Midrag"));
    card.appendChild(P("Les mêmes informations que le formulaire de connexion Midrag. Elles restent dans ce navigateur."));
    card.appendChild(L("Code fournisseur (קוד ספק)"));
    const spId = I(creds.spId, "12345", "numeric"); card.appendChild(spId);
    card.appendChild(L("Téléphone (05XXXXXXXX)"));
    const phone = I(creds.phoneNumber, "0501234567", "numeric"); card.appendChild(phone);
    card.appendChild(L("N° entreprise (עוסק/חברה)"));
    const company = I(creds.companyNumber, "", "numeric"); card.appendChild(company);

    card.appendChild(L("Recevoir le code par"));
    const method = el("div", "display:flex;gap:8px;margin-bottom:12px");
    let sendMethod = creds.sendMethod || 1;
    [[1, "SMS"], [2, "WhatsApp"]].forEach(([value, label]) => {
      const b = B(label, sendMethod === value);
      b.style.marginBottom = "0";
      b.addEventListener("click", () => {
        sendMethod = value;
        Array.from(method.children).forEach((child, i) => {
          const on = (i === 0 ? 1 : 2) === sendMethod;
          child.style.background = on ? "#a3134f" : "#ececef";
          child.style.color = on ? "#fff" : "#1c1c1e";
        });
      });
      method.appendChild(b);
    });
    card.appendChild(method);

    const send = B("Recevoir le code", true);
    send.addEventListener("click", async () => {
      const values = {
        spId: Number(String(spId.value).trim()),
        phoneNumber: String(phone.value).replace(/[-\s]/g, ""),
        companyNumber: String(company.value).trim(),
      };
      if (!values.spId || !values.phoneNumber || !values.companyNumber) {
        say("Remplis les trois champs.", "err"); return;
      }
      if (!/^05\d{8}$/.test(values.phoneNumber)) {
        say("Le téléphone doit faire 10 chiffres et commencer par 05.", "err"); return;
      }
      send.disabled = true;
      say("Envoi du code…");
      try {
        const uuid = await post("Account/Login", values);
        await post("Account/SendCode", { ...values, uuid, sendMethod });
        try { localStorage.setItem(CREDS_KEY, JSON.stringify({ ...values, sendMethod })); } catch (e) { /* mode privé */ }
        creds = { ...values, sendMethod };
        render(codeView, { values, uuid, sendMethod });
        say("Code envoyé par " + (sendMethod === 2 ? "WhatsApp" : "SMS") + ".", "ok");
      } catch (e) {
        say(e.message, "err");
        send.disabled = false;
      }
    });
    card.appendChild(send);
  };

  const codeView = ({ values, uuid, sendMethod }) => {
    card.appendChild(H("Code reçu ?"));
    card.appendChild(P("Les 6 chiffres envoyés au " + values.phoneNumber + "."));
    const code = I("", "123456", "numeric");
    code.maxLength = 6;
    card.appendChild(code);

    const validate = B("Valider et afficher le token", true);
    validate.addEventListener("click", async () => {
      const verificationCode = String(code.value).trim();
      if (!/^\d{6}$/.test(verificationCode)) { say("Le code fait 6 chiffres.", "err"); return; }
      validate.disabled = true;
      say("Vérification…");
      try {
        const token = await post("Account/Token", { spId: values.spId, verificationCode, uuid });
        if (!token || typeof token !== "string") throw new Error("Midrag n'a pas renvoyé de token.");
        render(tokenView, { token });
        say("");
      } catch (e) {
        say(e.message, "err");
        validate.disabled = false;
      }
    });
    card.appendChild(validate);

    const again = B("Renvoyer un code");
    again.addEventListener("click", async () => {
      again.disabled = true;
      say("Nouvel envoi…");
      try {
        await post("Account/SendCode", { ...values, uuid, sendMethod });
        say("Nouveau code envoyé.", "ok");
      } catch (e) { say(e.message, "err"); }
      again.disabled = false;
    });
    card.appendChild(again);

    const back = B("← Changer d'identifiants");
    back.addEventListener("click", () => { render(loginView); say(""); });
    card.appendChild(back);
  };

  const tokenView = ({ token }) => {
    card.appendChild(H("Token récupéré ✅"));
    const expiry = expiryOf(token);
    card.appendChild(P(expiry
      ? "Valable jusqu'au " + expiry.toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" })
      : "Date d'expiration illisible — colle-le quand même, la page de configuration te le dira."));
    const area = el("textarea", "width:100%;height:110px;padding:10px;border:1px solid #dcdce0;border-radius:8px;font-size:12px;font-family:monospace;margin-bottom:10px;background:#fff;color:#1c1c1e");
    area.value = token;
    area.readOnly = true;
    card.appendChild(area);

    const copy = B("Copier le token", true);
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(token);
        say("Token copié — colle-le dans la page de configuration.", "ok");
      } catch (e) {
        area.focus(); area.select();
        say(document.execCommand("copy")
          ? "Token copié."
          : "Copie impossible : sélectionne le texte ci-dessus et copie-le à la main.", "ok");
      }
    });
    card.appendChild(copy);

    const open = B("Ouvrir la page de configuration ↗");
    open.addEventListener("click", () => window.open(CONFIG_PAGE, "_blank", "noopener"));
    card.appendChild(open);
  };

  render(loginView);
})();
