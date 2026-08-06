/**
 * Tests v0.5.1.b — Sécurité + déploiement production
 * Vérifie la présence des artéfacts et leur cohérence structurelle.
 */
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const ROOT = path.resolve(__dirname, "..");
const readApp = (p) => fs.readFileSync(path.join(ROOT, "..", p), "utf8");
let passed = 0, failed = 0;
const t = (n, fn) => { try { fn(); console.log("  ✓", n); passed++; }
                       catch (e) { console.log("  ✗", n, "\n    ", e.message); failed++; } };

console.log("v0.5.1.b — Sécurité + production\n");

console.log("[Nginx]");
const nginx = readApp("deploy-app/nginx.conf");
t("Terminaison HTTPS (listen 443 ssl http2)", () =>
    assert.ok(/listen 443 ssl http2/.test(nginx)));
t("Redirection HTTP → HTTPS", () =>
    assert.ok(/return 301 https:\/\/\$host\$request_uri/.test(nginx)));
t("Challenge Let's Encrypt (ACME HTTP-01) préservé en clair", () =>
    assert.ok(/\/\.well-known\/acme-challenge\//.test(nginx)));
t("HSTS max-age=31536000 includeSubDomains preload", () =>
    assert.ok(/Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"/.test(nginx)));
t("X-Frame-Options DENY", () =>
    assert.ok(/X-Frame-Options "DENY"/.test(nginx)));
t("X-Content-Type-Options nosniff", () =>
    assert.ok(/X-Content-Type-Options "nosniff"/.test(nginx)));
t("Referrer-Policy strict-origin-when-cross-origin", () =>
    assert.ok(/Referrer-Policy "strict-origin-when-cross-origin"/.test(nginx)));
t("Permissions-Policy restrictive (géo/micro/paiement/usb)", () =>
    assert.ok(/Permissions-Policy .*geolocation=\(\).*microphone=\(\).*payment=\(\)/.test(nginx)));
t("Content-Security-Policy avec frame-ancestors 'none'", () =>
    assert.ok(/Content-Security-Policy.*frame-ancestors 'none'/.test(nginx)));
t("Rate limiting login 5r/min", () =>
    assert.ok(/limit_req_zone.*zone=login_zone:10m rate=5r\/m/.test(nginx)));
t("Rate limiting API générale", () =>
    assert.ok(/limit_req_zone.*zone=api_zone:10m rate=100r\/s/.test(nginx)));
t("TLS 1.2 + 1.3 uniquement", () =>
    assert.ok(/ssl_protocols TLSv1\.2 TLSv1\.3;/.test(nginx)));
t("OCSP stapling activé", () =>
    assert.ok(/ssl_stapling on;/.test(nginx)));
t("Reverse-proxy /api → backend:8001", () =>
    assert.ok(/proxy_pass http:\/\/backend:8001/.test(nginx)));
t("Reverse-proxy /go2rtc → go2rtc:1984", () =>
    assert.ok(/proxy_pass http:\/\/go2rtc:1984/.test(nginx)));

console.log("\n[docker-compose.prod.yml]");
const prod = readApp("deploy-app/docker-compose.prod.yml");
t("Service nginx présent (nginx:1.27-alpine)", () =>
    assert.ok(/image: nginx:1\.27-alpine/.test(prod)));
t("Service certbot (Let's Encrypt auto-renew)", () =>
    assert.ok(/image: certbot\/certbot:latest/.test(prod)));
t("Backend port 8001 fermé en direct", () =>
    assert.ok(/ports: !reset \[\]/.test(prod)));
t("JWT_SECRET obligatoire (?requis)", () =>
    assert.ok(/JWT_SECRET:\?JWT_SECRET requis/.test(prod)));
t("ADMIN_PASSWORD obligatoire", () =>
    assert.ok(/ADMIN_PASSWORD:\?ADMIN_PASSWORD requis/.test(prod)));
t("MGVMS_DOMAIN obligatoire", () =>
    assert.ok(/MGVMS_DOMAIN:\?MGVMS_DOMAIN requis/.test(prod)));
t("CORS_ORIGINS restreint au domaine prod", () =>
    assert.ok(/CORS_ORIGINS: https:\/\/\$\{MGVMS_DOMAIN\}/.test(prod)));
t("Cookie secure forcé en prod", () =>
    assert.ok(/MGVMS_COOKIE_SECURE: "true"/.test(prod)));
t("Volume letsencrypt partagé nginx ↔ certbot", () =>
    assert.ok(/letsencrypt:/.test(prod) && /certbot_www:/.test(prod)));
t("Ports 80 + 443 exposés", () =>
    assert.ok(/"80:80"/.test(prod) && /"443:443"/.test(prod)));

console.log("\n[Backend hardening]");
const server = readApp("backend/server.py");
t("TrustedHostMiddleware importé", () =>
    assert.ok(/from starlette\.middleware\.trustedhost import TrustedHostMiddleware/.test(server)));
t("TrustedHostMiddleware activé si MGVMS_TRUSTED_HOSTS défini", () =>
    assert.ok(/MGVMS_TRUSTED_HOSTS/.test(server) && /TrustedHostMiddleware, allowed_hosts=/.test(server)));

console.log("\n[Secrets — aucun défaut sensible en dur]");
const auth = readApp("backend/auth.py");
t("JWT_SECRET lu depuis os.environ, jamais de fallback en dur", () =>
    assert.ok(/os\.environ\["JWT_SECRET"\]/.test(auth),
              "JWT_SECRET DOIT être fail-fast (KeyError si absent)"));

console.log("\n[Rate limiting déjà en place côté backend]");
const security = readApp("backend/security.py");
t("Rate limiting présent (security.py)", () =>
    assert.ok(/rate.limit|LoginAttempt|brute/i.test(security)));

console.log(`\nRésultat : ${passed} passés, ${failed} échoués`);
process.exit(failed === 0 ? 0 : 1);
