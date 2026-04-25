import { useMemo, useState } from "react";

const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

function LoginPage() {
    const [mode, setMode] = useState("login");
    const [name, setName] = useState("");
    const [email, setEmail] = useState("researcher@pera.swarm");
    const [phone, setPhone] = useState("");
    const [password, setPassword] = useState("");
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
            const endpoint = mode === "login" ? "/users/login" : "/users/register";
            const payload =
                mode === "login"
                    ? { email, password }
                    : { name, email, phone, password };

            const response = await fetch(`${apiBase}${endpoint}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || "Request failed");
            }

            if (mode === "login") {
                if (data.token) {
                    localStorage.setItem("authToken", data.token);
                }
                setMessage("Login successful.");
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
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                background: "#f5f5f2",
            }}
        >
            <div
                style={{
                    background: "linear-gradient(180deg, #fafaf9 0%, #f2f2ef 100%)",
                    borderRight: "1px solid #dfdfd7",
                    padding: "40px 56px",
                    display: "flex",
                    flexDirection: "column",
                    position: "relative",
                    overflow: "hidden",
                }}
            >
                <PeraSwarmMark size={26} />

                <div style={{ flex: 1, display: "flex", alignItems: "center", marginTop: 40 }}>
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
                                letterSpacing: "-0.02em",
                                fontWeight: 600,
                                margin: "0 0 20px",
                                maxWidth: 520,
                                color: "#151718",
                            }}
                        >
                            One framework. Every robot in the lab.
                        </h1>
                        <p
                            style={{
                                fontSize: 15,
                                lineHeight: 1.55,
                                color: "#555955",
                                maxWidth: 460,
                                margin: 0,
                            }}
                        >
                            Control drones, ground robots and mixed-reality agents from a
                            single browser. Author behaviours visually, run them remotely,
                            study the swarm.
                        </p>
                    </div>
                </div>

                <div
                    style={{
                        fontSize: 11.5,
                        color: "#8e918d",
                        zIndex: 2,
                        letterSpacing: "0.04em",
                    }}
                >
                    v0.3.1 · build 2304-a · swarm-core.pera.lk
                </div>
            </div>

            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: 40,
                    background: "#ffffff",
                }}
            >
                <form onSubmit={handleSubmit} style={{ width: "100%", maxWidth: 380 }}>
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

                    <div
                        style={{
                            fontSize: 11,
                            letterSpacing: "0.1em",
                            color: "#6f726e",
                            textTransform: "uppercase",
                            fontWeight: 600,
                            marginBottom: 8,
                        }}
                    >
                        {mode === "login" ? "Sign in" : "Sign up"}
                    </div>
                    <h2
                        style={{
                            fontSize: 24,
                            fontWeight: 600,
                            letterSpacing: "-0.01em",
                            margin: "0 0 6px",
                        }}
                    >
                        {pageTitle}
                    </h2>
                    <p style={{ color: "#555955", margin: "0 0 24px", fontSize: 13.5 }}>
                        {pageText}
                    </p>

                    {mode === "register" ? (
                        <div style={{ marginBottom: 12 }}>
                            <label style={labelStyle}>Name</label>
                            <input
                                style={inputStyle}
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                required
                            />
                        </div>
                    ) : null}

                    <div style={{ marginBottom: 12 }}>
                        <label style={labelStyle}>Email</label>
                        <input
                            style={inputStyle}
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                        />
                    </div>

                    {mode === "register" ? (
                        <div style={{ marginBottom: 12 }}>
                            <label style={labelStyle}>Phone</label>
                            <input
                                style={inputStyle}
                                value={phone}
                                onChange={(e) => setPhone(e.target.value)}
                                required
                            />
                        </div>
                    ) : null}

                    <div style={{ marginBottom: 18 }}>
                        <label style={labelStyle}>Password</label>
                        <input
                            style={inputStyle}
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                        />
                    </div>

                    {message ? (
                        <div style={successStyle}>{message}</div>
                    ) : null}
                    {error ? <div style={errorStyle}>{error}</div> : null}

                    <button
                        style={submitButtonStyle}
                        type="submit"
                        disabled={loading}
                    >
                        {loading
                            ? "Please wait..."
                            : mode === "login"
                                ? "Enter Swarm Console"
                                : "Create account"}
                    </button>
                </form>
            </div>

            <style>{`
				@media (max-width: 900px) {
					div[data-login-root="true"] {
						grid-template-columns: 1fr;
					}
				}
			`}</style>
        </div>
    );
}

function PeraSwarmMark({ size = 26 }) {
    return (
        <div
            style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 10,
                color: "#131516",
                fontWeight: 700,
            }}
        >
            <div
                style={{
                    width: size,
                    height: size,
                    borderRadius: 7,
                    background: "linear-gradient(135deg, #111 0%, #3a5fbd 100%)",
                }}
            />
            <span style={{ fontSize: 16 }}>PeraSwarm</span>
        </div>
    );
}

function tabButton(active) {
    return {
        border: "1px solid #d6d7d1",
        background: active ? "#111" : "#fff",
        color: active ? "#fff" : "#222",
        fontSize: 12,
        fontWeight: 600,
        borderRadius: 9,
        padding: "8px 14px",
        cursor: "pointer",
    };
}

const labelStyle = {
    display: "block",
    fontSize: 12,
    color: "#6f726e",
    marginBottom: 6,
    fontWeight: 600,
};

const inputStyle = {
    width: "100%",
    height: 40,
    border: "1px solid #d7d9d3",
    borderRadius: 10,
    padding: "0 12px",
    fontSize: 14,
    outline: "none",
};

const submitButtonStyle = {
    width: "100%",
    height: 42,
    border: "none",
    borderRadius: 10,
    background: "#1d4ed8",
    color: "#fff",
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer",
};

const successStyle = {
    marginBottom: 12,
    fontSize: 12.5,
    color: "#0a7f2e",
    background: "#edfaef",
    border: "1px solid #bee8c6",
    borderRadius: 8,
    padding: "8px 10px",
};

const errorStyle = {
    marginBottom: 12,
    fontSize: 12.5,
    color: "#9f1239",
    background: "#fff1f2",
    border: "1px solid #fecdd3",
    borderRadius: 8,
    padding: "8px 10px",
};

export default LoginPage;
