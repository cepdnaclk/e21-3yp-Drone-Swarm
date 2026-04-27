import { useMemo, useState } from "react";

const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

function LoginPage({ onLoginSuccess }) {
    const [mode, setMode] = useState("login");
    const [name, setName] = useState("");
    const [email, setEmail] = useState("researcher@pera.swarm");
    const [phone, setPhone] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState("");
    const [error, setError] = useState("");

    const pageTitle = useMemo(() => {
        return mode === "login" ? "Welcome back" : "Create an account";
    }, [mode]);

    const pageText = useMemo(() => {
        return mode === "login"
            ? "Use your researcher credentials to enter the control plane."
            : "Register your details. An admin must approve your account before login.";
    }, [mode]);

    async function handleSubmit(e) {
        e.preventDefault();
        setLoading(true);
        setMessage("");
        setError("");

        try {
            if (mode === "register" && password !== confirmPassword) {
                throw new Error("Passwords do not match.");
            }

            const endpoint =
                mode === "login" ? "/users/login" : "/users/register";

            const payload =
                mode === "login"
                    ? { email, password }
                    : { name, email, phone, password };

            const response = await fetch(`${apiBase}${endpoint}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include", // 🔥 IMPORTANT (cookie auth)
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || "Request failed");
            }

            if (mode === "login") {
                setMessage("Login successful.");

                // no token handling anymore
                if (typeof onLoginSuccess === "function") {
                    onLoginSuccess();
                }
            } else {
                setMessage(data.message || "Registration successful.");
                setMode("login");
            }
        } catch (submitError) {
            setError(submitError.message || "Something went wrong.");
        } finally {
            setLoading(false);
        }
    }

    return (
        <div
            data-login-root="true"
            style={{
                minHeight: "100vh",
                width: "100vw",
                marginLeft: "calc(50% - 50vw)",
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                background: "#f5f5f2",
                colorScheme: "light",
                color: "#111827",
            }}
        >
            {/* LEFT PANEL */}
            <div
                style={{
                    background: "linear-gradient(180deg, #fafaf9 0%, #f2f2ef 100%)",
                    borderRight: "1px solid #dfdfd7",
                    padding: "40px 56px",
                    display: "flex",
                    flexDirection: "column",
                }}
            >
                <PeraSwarmMark size={26} />

                <div style={{ flex: 1, display: "flex", alignItems: "center" }}>
                    <div>
                        <div
                            style={{
                                fontSize: 11,
                                letterSpacing: "0.12em",
                                color: "#6f726e",
                                textTransform: "uppercase",
                                fontWeight: 600,
                                marginBottom: 16,
                            }}
                        >
                            Remote swarm robotics · University of Peradeniya
                        </div>

                        <h1
                            style={{
                                fontSize: 42,
                                lineHeight: 1.08,
                                fontWeight: 600,
                                margin: "0 0 20px",
                                color: "#151718",
                            }}
                        >
                            One framework. Every robot in the lab.
                        </h1>

                        <p style={{ fontSize: 15, color: "#555955" }}>
                            Control drones, ground robots and AI agents from a single browser.
                        </p>
                    </div>
                </div>
            </div>

            {/* RIGHT PANEL */}
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: 40,
                    background: "#ffffff",
                }}
            >
                <form
                    onSubmit={handleSubmit}
                    style={{ width: "100%", maxWidth: 380 }}
                >
                    <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
                        <button
                            type="button"
                            onClick={() => setMode("login")}
                            style={tabButton(mode === "login")}
                        >
                            Login
                        </button>
                        <button
                            type="button"
                            onClick={() => setMode("register")}
                            style={tabButton(mode === "register")}
                        >
                            Register
                        </button>
                    </div>

                    <h2 style={{ fontSize: 24, marginBottom: 6 }}>
                        {pageTitle}
                    </h2>

                    <p style={{ fontSize: 13, marginBottom: 24, color: "#374151" }}>
                        {pageText}
                    </p>

                    {mode === "register" && (
                        <div style={{ marginBottom: 12 }}>
                            <label style={labelStyle}>Name</label>
                            <input
                                style={inputStyle}
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                required
                            />
                        </div>
                    )}

                    <div style={{ marginBottom: 12 }}>
                        <label style={labelStyle}>Email</label>
                        <input
                            style={inputStyle}
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                        />
                    </div>

                    {mode === "register" && (
                        <div style={{ marginBottom: 12 }}>
                            <label style={labelStyle}>Phone</label>
                            <input
                                style={inputStyle}
                                value={phone}
                                onChange={(e) => setPhone(e.target.value)}
                                required
                            />
                        </div>
                    )}

                    <div style={{ marginBottom: 12 }}>
                        <label style={labelStyle}>Password</label>
                        <input
                            type="password"
                            style={inputStyle}
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                        />
                    </div>

                    {mode === "register" && (
                        <div style={{ marginBottom: 12 }}>
                            <label style={labelStyle}>Confirm Password</label>
                            <input
                                type="password"
                                style={inputStyle}
                                value={confirmPassword}
                                onChange={(e) =>
                                    setConfirmPassword(e.target.value)
                                }
                                required
                            />
                        </div>
                    )}

                    {message && <div style={successStyle}>{message}</div>}
                    {error && <div style={errorStyle}>{error}</div>}

                    <button
                        type="submit"
                        disabled={loading}
                        style={submitButtonStyle}
                    >
                        {loading
                            ? "Please wait..."
                            : mode === "login"
                            ? "Enter Swarm Console"
                            : "Create account"}
                    </button>
                </form>
            </div>
        </div>
    );
}

/* UI helpers */
function PeraSwarmMark({ size = 26 }) {
    return (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div
                style={{
                    width: size,
                    height: size,
                    borderRadius: 7,
                    background: "linear-gradient(135deg, #111, #3a5fbd)",
                }}
            />
            <strong>PeraSwarm</strong>
        </div>
    );
}

function tabButton(active) {
    return {
        padding: "8px 14px",
        borderRadius: 8,
        border: "1px solid #ccc",
        background: active ? "#111" : "#fff",
        color: active ? "#fff" : "#000",
        cursor: "pointer",
    };
}

const labelStyle = { fontSize: 12, fontWeight: 600, marginBottom: 6 };
const inputStyle = {
    width: "100%",
    padding: "10px",
    borderRadius: 8,
    border: "1px solid #ccc",
};

const submitButtonStyle = {
    width: "100%",
    padding: "10px",
    borderRadius: 8,
    background: "#1d4ed8",
    color: "#fff",
    border: "none",
    fontWeight: 600,
    cursor: "pointer",
};

const successStyle = {
    padding: 8,
    background: "#e6ffed",
    border: "1px solid #b7ebc6",
    marginBottom: 10,
};

const errorStyle = {
    padding: 8,
    background: "#ffe6e6",
    border: "1px solid #ffb3b3",
    marginBottom: 10,
};

export default LoginPage;