const express = require("express");
const mongoose = require("mongoose");
const { config } = require("dotenv");
const userRoutes = require("./routes/user/userRoutes");
const adminRoutes = require("./routes/admin/adminRoutes");


config();

const app = express();
const PORT = process.env.PORT || 5000;
const MONGODB_URI = process.env.MONGODB_URI || process.env.DATABASE_URL;
const ALLOWED_ORIGIN = process.env.CORS_ORIGIN || "http://localhost:5173";

app.use((req, res, next) => {
    res.header("Access-Control-Allow-Origin", ALLOWED_ORIGIN);
    res.header("Access-Control-Allow-Headers", "Content-Type, Authorization");
    res.header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS");

    if (req.method === "OPTIONS") {
        return res.sendStatus(204);
    }

    return next();
});
app.use(express.json());
app.use("/api/users", userRoutes);
app.use("/api/admin", adminRoutes);

app.get("/health", (_req, res) => {
    res.status(200).json({ ok: true, service: "backend" });
});

async function startServer() {
    if (!MONGODB_URI) {
        throw new Error("Missing env var: MONGODB_URI (or DATABASE_URL)");
    }

    await mongoose.connect(MONGODB_URI, {
        dbName: process.env.MONGODB_DB_NAME || "droneswarm",
    });


    app.listen(PORT, () => {
        console.log(`Server running on port ${PORT}`);
        console.log("MongoDB connected and users collection is ready.");
    });
}

startServer().catch((error) => {
    console.error("Startup failed:", error.message);
    process.exit(1);
});
