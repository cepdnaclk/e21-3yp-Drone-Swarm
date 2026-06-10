const express = require("express");
const jwt = require("jsonwebtoken");
const { isAdminPayload } = require("../../middleware/auth");

const router = express.Router();

/* 🔍 CURRENT USER */
router.get("/me", (req, res) => {
    const token = req.cookies?.token;

    if (!token) {
        return res.status(200).json({ ok: true, user: null });
    }

    try {
        const payload = jwt.verify(
            token,
            process.env.JWT_SECRET || "dev_jwt_secret_change_me"
        );

        return res.json({
            ok: true,
            user: {
                ...payload,
                isAdmin: isAdminPayload(payload),
            },
        });
    } catch {
        return res.status(200).json({ ok: true, user: null });
    }
});

/* 🚪 LOGOUT */
router.post("/logout", (req, res) => {
    res.clearCookie("token", {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
    });
    res.json({ ok: true });
});

module.exports = router;
