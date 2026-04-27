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

    async function handleSubmit(event) {
        event.preventDefault();
        setLoading(true);
        setMessage("");
        setError("");

        try {
            if (mode === "register" && password !== confirmPassword) {
                throw new Error("Passwords do not match.");
            }

            const endpoint = mode === "login" ? "/users/login" : "/users/register";
            const payload = mode === "login"
                ? { email, password }
                : { name, email, phone, password };

            const response = await fetch(`${apiBase}${endpoint}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || "Request failed");
            }

            if (mode === "login") {
                setMessage("Login successful.");

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
        <main className="page-shell page-shell--login">
            <section className="brand-panel">
                <PeraSwarmMark size={26} />

                <div className="brand-copy">
                    <p className="eyebrow">Remote swarm robotics · University of Peradeniya</p>
                    <h1>One framework. Every robot in the lab.</h1>
                    <p className="brand-summary">Control drones, ground robots and AI agents from a single browser with a workflow designed for operators and researchers.</p>
                </div>

                <ul className="feature-list">
                    <li>
                        Secure access
                        <span>Cookie-based authentication for the control plane.</span>
                    </li>
                    <li>
                        Live project routing
                        <span>Move from login to active project workspaces instantly.</span>
                    </li>
                    <li>
                        Operational clarity
                        <span>Structured, high-contrast screens that work in a lab setting.</span>
                    </li>
                </ul>
            </section>

            <section className="auth-panel">
                <form onSubmit={handleSubmit} className="auth-card">
                    <div className="tab-row">
                        <button
                            type="button"
                            onClick={() => setMode("login")}
                            className={`tab-button ${mode === "login" ? "is-active" : ""}`}
                        >
                            Login
                        </button>
                        <button
                            type="button"
                            onClick={() => setMode("register")}
                            className={`tab-button ${mode === "register" ? "is-active" : ""}`}
                        >
                            Register
                        </button>
                    </div>

                    <h2 className="auth-heading">{pageTitle}</h2>
                    <p className="auth-copy">{pageText}</p>

                    {mode === "register" && (
                        <label className="field">
                            <span className="field-label">Name</span>
                            <input value={name} onChange={(event) => setName(event.target.value)} required />
                        </label>
                    )}

                    <label className="field">
                        <span className="field-label">Email</span>
                        <input value={email} onChange={(event) => setEmail(event.target.value)} required />
                    </label>

                    {mode === "register" && (
                        <label className="field">
                            <span className="field-label">Phone</span>
                            <input value={phone} onChange={(event) => setPhone(event.target.value)} required />
                        </label>
                    )}

                    <label className="field">
                        <span className="field-label">Password</span>
                        <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
                    </label>

                    {mode === "register" && (
                        <label className="field">
                            <span className="field-label">Confirm Password</span>
                            <input
                                type="password"
                                value={confirmPassword}
                                onChange={(event) => setConfirmPassword(event.target.value)}
                                required
                            />
                        </label>
                    )}

                    {message && <div className="alert alert-success">{message}</div>}
                    {error && <div className="alert alert-error">{error}</div>}

                    <button type="submit" disabled={loading} className="primary-button">
                        {loading ? "Please wait..." : mode === "login" ? "Enter Swarm Console" : "Create account"}
                    </button>
                </form>
            </section>
        </main>
    );
}

function PeraSwarmMark({ size = 26 }) {
    return (
        <div className="brand-mark">
            <div className="brand-mark-badge" style={{ width: size, height: size }} />
            <strong>PeraSwarm</strong>
        </div>
    );
}

export default LoginPage;