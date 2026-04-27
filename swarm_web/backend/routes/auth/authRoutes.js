// authRoutes.js
const express = require("express");
const jwt = require("jsonwebtoken");

const router = express.Router();

/* 🔍 CURRENT USER */
router.get("/me", (req, res) => {
    const token = req.cookies?.token;

    // 1. If no token, return 200 OK but with user: null
    if (!token) {
        return res.status(200).json({ ok: true, user: null });
    }

    try {
        // 2. Added the fallback secret here as well to prevent crashes
        const payload = jwt.verify(
            token, 
            process.env.JWT_SECRET || "dev_jwt_secret_change_me"
        );

        return res.json({
            ok: true,
            user: payload,
        });
    } catch {
        // 3. If token is expired/invalid, also return 200 OK with user: null
        return res.status(200).json({ ok: true, user: null });
    }
});

/* 🚪 LOGOUT */
router.post("/logout", (req, res) => {
    // 4. Match the cookie settings from login for a clean logout
    res.clearCookie("token", {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production", 
        sameSite: "lax",
    });
    res.json({ ok: true });
});

module.exports = router;