const express = require("express");
const mongoose = require("mongoose");
const User = require("../../models/User");

const router = express.Router();

router.use((req, res, next) => {
    const adminSecret = process.env.ADMIN_SECRET;

    // If ADMIN_SECRET is set, requests must include x-admin-secret.
    if (adminSecret && req.header("x-admin-secret") !== adminSecret) {
        return res.status(401).json({
            ok: false,
            message: "Unauthorized admin request.",
        });
    }

    return next();
});

router.patch("/verify-user", async (req, res) => {
    try {
        const { userId, email } = req.body;

        if (!userId && !email) {
            return res.status(400).json({
                ok: false,
                message: "userId or email is required.",
            });
        }

        let query;
        if (userId) {
            if (!mongoose.Types.ObjectId.isValid(userId)) {
                return res.status(400).json({
                    ok: false,
                    message: "Invalid userId.",
                });
            }

            query = { _id: userId };
        } else {
            query = { email: String(email).toLowerCase() };
        }

        const user = await User.findOne(query);
        if (!user) {
            return res.status(404).json({
                ok: false,
                message: "User not found.",
            });
        }

        if (user.isVerified) {
            return res.status(200).json({
                ok: true,
                message: "User is already verified.",
                user: {
                    id: user._id,
                    name: user.name,
                    email: user.email,
                    phone: user.phone,
                    isVerified: user.isVerified,
                },
            });
        }

        user.isVerified = true;
        await user.save();

        return res.status(200).json({
            ok: true,
            message: "User verified successfully.",
            user: {
                id: user._id,
                name: user.name,
                email: user.email,
                phone: user.phone,
                isVerified: user.isVerified,
            },
        });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to verify user.",
            error: error.message,
        });
    }
});

module.exports = router;
