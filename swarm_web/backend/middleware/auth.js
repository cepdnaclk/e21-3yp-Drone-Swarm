const jwt = require("jsonwebtoken");

function parseAdminEmails() {
    return String(process.env.ADMIN_EMAILS || "")
        .split(",")
        .map((entry) => entry.trim().toLowerCase())
        .filter(Boolean);
}

function getTokenFromRequest(req) {
    const authHeader = req.header("authorization") || req.header("Authorization");
    if (!authHeader || !authHeader.startsWith("Bearer ")) {
        return "";
    }

    return authHeader.slice("Bearer ".length).trim();
}

function isAdminPayload(payload) {
    if (!payload || typeof payload !== "object") {
        return false;
    }

    if (payload.isAdmin === true) {
        return true;
    }

    const email = String(payload.email || "").toLowerCase();
    if (!email) {
        return false;
    }

    return parseAdminEmails().includes(email);
}

function authenticateJWT(req, res, next) {
    const token = getTokenFromRequest(req);
    if (!token) {
        return res.status(401).json({
            ok: false,
            message: "Missing Bearer token.",
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

        return next();
    } catch (_error) {
        return res.status(401).json({
            ok: false,
            message: "Invalid or expired token.",
        });
    }
}

function requireAdminAccess(req, res, next) {
    const adminSecret = process.env.ADMIN_SECRET;
    const headerSecret = req.header("x-admin-secret");

    if (adminSecret && headerSecret && headerSecret === adminSecret) {
        return next();
    }

    const token = getTokenFromRequest(req);
    if (!token) {
        return res.status(401).json({
            ok: false,
            message: "Admin access requires a valid admin token or x-admin-secret.",
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

        return next();
    } catch (_error) {
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
