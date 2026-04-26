import { useMemo, useState } from "react";
import "./app-shell.css";

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
                if (typeof onLoginSuccess === "function") {
                    onLoginSuccess(data.token || "");
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
        <main className="auth-shell" data-login-root="true">
            <section className="auth-showcase">
                <PeraSwarmMark size={28} />

                <div className="auth-showcase-main">
                    <p className="auth-kicker">Remote swarm robotics · University of Peradeniya</p>
                    <h1>Professional control plane for autonomous swarm research.</h1>
                    <p>
                        Run field experiments, inspect live telemetry, and coordinate your
                        multi-agent workflows from a single secure console.
                    </p>

                    <div className="auth-metric-grid">
                        <article>
                            <strong>4+</strong>
                            <span>Camera streams</span>
                        </article>
                        <article>
                            <strong>Low-latency</strong>
                            <span>Indoor localization</span>
                        </article>
                        <article>
                            <strong>Role-based</strong>
                            <span>Access management</span>
                        </article>
                    </div>
                </div>

                <p className="auth-build">v0.3.1 · build 2304-a · swarm-core.pera.lk</p>
            </section>

            <section className="auth-panel-wrap">
                <form onSubmit={handleSubmit} className="auth-panel">
                    <div className="auth-mode-switch">
                        <button
                            type="button"
                            onClick={() => setMode("login")}
                            className={`auth-mode-btn ${mode === "login" ? "active" : ""}`}
                        >
                            Login
                        </button>
                        <button
                            type="button"
                            onClick={() => setMode("register")}
                            className={`auth-mode-btn ${mode === "register" ? "active" : ""}`}
                        >
                            Register
                        </button>
                    </div>

                    <p className="auth-form-kicker">{mode === "login" ? "Sign in" : "Sign up"}</p>
                    <h2>{pageTitle}</h2>
                    <p className="auth-form-copy">{pageText}</p>

                    {mode === "register" ? (
                        <div className="auth-field">
                            <label htmlFor="name">Name</label>
                            <input
                                id="name"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                required
                            />
                        </div>
                    ) : null}

                    <div className="auth-field">
                        <label htmlFor="email">Email</label>
                        <input
                            id="email"
                            type="text"
                            inputMode="email"
                            autoComplete="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                        />
                    </div>

                    {mode === "register" ? (
                        <div className="auth-field">
                            <label htmlFor="phone">Phone</label>
                            <input
                                id="phone"
                                value={phone}
                                onChange={(e) => setPhone(e.target.value)}
                                required
                            />
                        </div>
                    ) : null}

                    <div className="auth-field">
                        <label htmlFor="password">Password</label>
                        <input
                            id="password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                        />
                    </div>

                    {mode === "register" ? (
                        <div className="auth-field">
                            <label htmlFor="confirmPassword">Confirm Password</label>
                            <input
                                id="confirmPassword"
                                type="password"
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                required
                            />
                        </div>
                    ) : null}

                    {message ? <div className="auth-alert success">{message}</div> : null}
                    {error ? <div className="auth-alert error">{error}</div> : null}

                    <button className="auth-submit" type="submit" disabled={loading}>
                        {loading
                            ? "Please wait..."
                            : mode === "login"
                                ? "Enter Swarm Console"
                                : "Create account"}
                    </button>
                </form>
            </section>
        </main>
    );
}

function PeraSwarmMark({ size = 26 }) {
    return (
        <div className="auth-brand">
            <div
                style={{
                    width: size,
                    height: size,
                }}
                className="auth-brand-dot"
            />
            <span>PeraSwarm</span>
        </div>
    );
}

export default LoginPage;
