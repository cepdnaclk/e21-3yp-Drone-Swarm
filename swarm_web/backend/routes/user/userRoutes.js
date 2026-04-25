const express = require("express");
const bcrypt = require("bcryptjs");
const crypto = require("crypto");
const jwt = require("jsonwebtoken");
const User = require("../../models/User");

const router = express.Router();

router.post("/register", async (req, res) => {
    try {
        const { name, email, phone, password } = req.body;

        if (!name || !email || !phone || !password) {
            return res.status(400).json({
                ok: false,
                message: "name, email, phone and password are required.",
            });
        }

        const existingUser = await User.findOne({ email: email.toLowerCase() });
        if (existingUser) {
            return res.status(409).json({
                ok: false,
                message: "User already exists with this email.",
            });
        }

        const hashedPassword = await bcrypt.hash(password, 10);
        const verificationToken = crypto.randomBytes(32).toString("hex");

        const user = await User.create({
            name,
            email: email.toLowerCase(),
            phone,
            password: hashedPassword,
            isVerified: false,
            verificationToken,
        });

        return res.status(201).json({
            ok: true,
            message: "User registered successfully. Please verify your account.",
            verificationToken:
                process.env.NODE_ENV === "production"
                    ? undefined
                    : user.verificationToken,
        });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to register user.",
            error: error.message,
        });
    }
});

router.get("/verify/:token", async (req, res) => {
    try {
        const { token } = req.params;

        if (!token) {
            return res.status(400).json({
                ok: false,
                message: "Verification token is required.",
            });
        }

        const user = await User.findOne({ verificationToken: token });
        if (!user) {
            return res.status(400).json({
                ok: false,
                message: "Invalid or expired verification token.",
            });
        }

        user.isVerified = true;
        user.verificationToken = undefined;
        await user.save();

        return res.status(200).json({
            ok: true,
            message: "User verified successfully.",
        });
    } catch (error) {
        return res.status(500).json({
            ok: false,
            message: "Failed to verify user.",
            error: error.message,
        });
    }
});

router.post("/login", async (req, res) => {
    try {
        const { email, password } = req.body;

        if (!email || !password) {
            return res.status(400).json({
                ok: false,
                message: "email and password are required.",
            });
        }

        const user = await User.findOne({ email: email.toLowerCase() });
        if (!user) {
            return res.status(401).json({
                ok: false,
                message: "Invalid email or password.",
            });
        }

        const passwordMatches = await bcrypt.compare(password, user.password);
        if (!passwordMatches) {
            return res.status(401).json({
                ok: false,
                message: "Invalid email or password.",
            });
        }

        if (!user.isVerified) {
            return res.status(403).json({
                ok: false,
                message: "Please verify your account before login.",
            });
        }

        const token = jwt.sign(
            { sub: user._id.toString(), email: user.email },
            process.env.JWT_SECRET || "dev_jwt_secret_change_me",
            { expiresIn: "7d" }
        );

        return res.status(200).json({
            ok: true,
            message: "Login successful.",
            token,
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
            message: "Failed to login.",
            error: error.message,
        });
    }
});

module.exports = router;
