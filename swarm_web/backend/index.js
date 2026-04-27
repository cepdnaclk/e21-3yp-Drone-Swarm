const express = require("express");
const mongoose = require("mongoose");
const { config } = require("dotenv");
const cors = require("cors");
const cookieParser = require("cookie-parser");

const userRoutes = require("./routes/user/userRoutes");
const adminRoutes = require("./routes/admin/adminRoutes");
const projectRoutes = require("./routes/project/projectRoutes");
const gatewayRoutes = require("./routes/gateway/gatewayRoutes");
const authRoutes = require("./routes/auth/authRoutes");

config();

const app = express();
const PORT = process.env.PORT || 5000;
const MONGODB_URI = process.env.MONGODB_URI || process.env.DATABASE_URL;

// ✅ Allowed origins
const ALLOWED_ORIGINS = [
  process.env.CORS_ORIGIN || "http://localhost:5173",
  "http://localhost:7001"
];

// ✅ CORS setup
app.use(
  cors({
    origin: function (origin, callback) {
      // allow Postman, curl, server-to-server calls
      if (!origin || ALLOWED_ORIGINS.includes(origin)) {
        callback(null, true);
      } else {
        callback(new Error("Not allowed by CORS: " + origin));
      }
    },
    methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allowedHeaders: ["Content-Type", "Authorization"],
    credentials: true
  })
);

// ⚡ Body parser
app.use(express.json());

// ================= Routes =================
app.use(cookieParser());
app.use("/api/users", userRoutes);
app.use("/api/admin", adminRoutes);
app.use("/api/projects", projectRoutes);
app.use("/api/gateway", gatewayRoutes);
app.use("/api/auth", authRoutes); // New auth routes
app.use(cookieParser());

// ================= Health Check =================
app.get("/health", (_req, res) => {
  res.status(200).json({
    ok: true,
    service: "backend",
    timestamp: new Date().toISOString()
  });
});

// ❌ DO NOT use app.options("*", cors())
// (caused your crash with path-to-regexp)

// ================= Start Server =================
async function startServer() {
  if (!MONGODB_URI) {
    throw new Error("Missing env var: MONGODB_URI (or DATABASE_URL)");
  }

  await mongoose.connect(MONGODB_URI, {
    dbName: process.env.MONGODB_DB_NAME || "droneswarm",
  });

  app.listen(PORT, () => {
    console.log(`🚀 Server running on http://localhost:${PORT}`);
    console.log("✅ MongoDB connected");
    console.log("🌐 Allowed origins:", ALLOWED_ORIGINS);
  });
}

startServer().catch((error) => {
  console.error("❌ Startup failed:", error.message);
  process.exit(1);
});