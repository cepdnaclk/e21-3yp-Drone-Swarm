const jwt = require("jsonwebtoken");

function parseAdminEmails() {
    return String(process.env.ADMIN_EMAILS || "")
        .split(",")
        .map((e) => e.trim().toLowerCase())
        .filter(Boolean);
}

// ✅ TOKEN FROM COOKIE (NEW)
function getTokenFromRequest(req) {
    // cookie-parser required in app.js
    return req.cookies?.token || "";
}

function isAdminPayload(payload) {
    if (!payload || typeof payload !== "object") return false;

    if (payload.isAdmin === true) return true;

    const email = String(payload.email || "").toLowerCase();
    if (!email) return false;

    return parseAdminEmails().includes(email);
}

// 🔐 AUTH MIDDLEWARE (COOKIE BASED)
function authenticateJWT(req, res, next) {
    const token = getTokenFromRequest(req);

    if (!token) {
        return res.status(401).json({
            ok: false,
            message: "Missing authentication cookie.",
        });
    }

    try {
        const payload = jwt.verify(
            token,
            process.env.JWT_SECRET || "dev_jwt_secret_change_me"
        );

        req.auth = {
            ...payload,
            isAdmin: isAdminPayload(payload),
        };

        next();
    } catch (err) {
        return res.status(401).json({
            ok: false,
            message: "Invalid or expired token.",
        });
    }
}

// 🔐 ADMIN MIDDLEWARE (COOKIE BASED)
function requireAdminAccess(req, res, next) {
    const adminSecret = process.env.ADMIN_SECRET;
    const headerSecret = req.header("x-admin-secret");

    // optional bypass (service-to-service)
    if (adminSecret && headerSecret && headerSecret === adminSecret) {
        return next();
    }

    const token = getTokenFromRequest(req);

    if (!token) {
        return res.status(401).json({
            ok: false,
            message: "Admin access requires authentication cookie.",
        });
    }

    try {
        const payload = jwt.verify(
            token,
            process.env.JWT_SECRET || "dev_jwt_secret_change_me"
        );

        if (!isAdminPayload(payload)) {
            return res.status(403).json({
                ok: false,
                message: "Admin role required.",
            });
        }

        req.auth = {
            ...payload,
            isAdmin: true,
        };

        next();
    } catch (err) {
        return res.status(401).json({
            ok: false,
            message: "Invalid or expired token.",
        });
    }
}

module.exports = {
    authenticateJWT,
    requireAdminAccess,
    isAdminPayload,
};