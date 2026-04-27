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
        return mode === "login" ? "Mission control access" : "Create a lab account";
    }, [mode]);

    const pageText = useMemo(() => {
        return mode === "login"
            ? "Use your researcher credentials to open the swarm console."
            : "Register your details. An administrator must approve the account before login.";
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
        <div className="auth-page shell-page">
            <div className="shell-page__glow" />
            <div className="shell-page__glow shell-page__glow--right" />

            <section className="auth-page__brand">
                <PeraSwarmMark />

                <div className="auth-page__hero">
                    <p className="shell-label">Remote swarm robotics · University of Peradeniya</p>
                    <h1 className="shell-title">One framework. Every robot in the lab.</h1>
                    <p className="shell-subtitle">
                        Control drones, ground robots and mixed-reality agents from a single
                        browser. Launch missions, inspect telemetry and move from experiment to
                        deployment without switching tools.
                    </p>

                    <div className="shell-kpis">
                        <div className="shell-kpi">
                            <span className="shell-kpi__value">24/7</span>
                            <span className="shell-kpi__label">Remote lab access</span>
                        </div>
                        <div className="shell-kpi">
                            <span className="shell-kpi__value">4D</span>
                            <span className="shell-kpi__label">Tracking and telemetry</span>
                        </div>
                        <div className="shell-kpi">
                            <span className="shell-kpi__value">1</span>
                            <span className="shell-kpi__label">Unified operator console</span>
                        </div>
                    </div>
                </div>

                <div className="auth-page__footer">v0.3.1 · build 2304-a · swarm-core.pera.lk</div>
            </section>

            <section className="auth-page__panel-wrap">
                <form onSubmit={handleSubmit} className="auth-panel shell-card">
                    <div className="auth-panel__tabs">
                        <button
                            type="button"
                            onClick={() => setMode("login")}
                            className={mode === "login" ? "auth-tab auth-tab--active" : "auth-tab"}
                        >
                            Login
                        </button>
                        <button
                            type="button"
                            onClick={() => setMode("register")}
                            className={mode === "register" ? "auth-tab auth-tab--active" : "auth-tab"}
                        >
                            Register
                        </button>
                    </div>

                    <p className="shell-label">{mode === "login" ? "Sign in" : "Sign up"}</p>
                    <h2 className="auth-panel__title">{pageTitle}</h2>
                    <p className="auth-panel__subtitle">{pageText}</p>

                    {mode === "register" ? (
                        <div className="shell-field">
                            <label htmlFor="register-name">Name</label>
                            <input
                                id="register-name"
                                className="shell-input"
                                value={name}
                                onChange={(event) => setName(event.target.value)}
                                required
                            />
                        </div>
                    ) : null}

                    <div className="shell-field">
                        <label htmlFor="auth-email">Email</label>
                        <input
                            id="auth-email"
                            className="shell-input"
                            type="text"
                            inputMode="email"
                            autoComplete="email"
                            value={email}
                            onChange={(event) => setEmail(event.target.value)}
                            required
                        />
                    </div>

                    {mode === "register" ? (
                        <div className="shell-field">
                            <label htmlFor="register-phone">Phone</label>
                            <input
                                id="register-phone"
                                className="shell-input"
                                value={phone}
                                onChange={(event) => setPhone(event.target.value)}
                                required
                            />
                        </div>
                    ) : null}

                    <div className="shell-field">
                        <label htmlFor="auth-password">Password</label>
                        <input
                            id="auth-password"
                            className="shell-input"
                            type="password"
                            value={password}
                            onChange={(event) => setPassword(event.target.value)}
                            required
                        />
                    </div>

                    {mode === "register" ? (
                        <div className="shell-field">
                            <label htmlFor="register-confirm-password">Confirm password</label>
                            <input
                                id="register-confirm-password"
                                className="shell-input"
                                type="password"
                                value={confirmPassword}
                                onChange={(event) => setConfirmPassword(event.target.value)}
                                required
                            />
                        </div>
                    ) : null}

                    {message ? <div className="shell-message shell-message--success">{message}</div> : null}
                    {error ? <div className="shell-message shell-message--error">{error}</div> : null}

                    <button className="shell-button auth-panel__submit" type="submit" disabled={loading}>
                        {loading
                            ? "Please wait..."
                            : mode === "login"
                                ? "Enter swarm console"
                                : "Create account"}
                    </button>
                </form>
            </section>
        </div>
    );
}

function PeraSwarmMark() {
    return (
        <div className="shell-mark">
            <div className="shell-mark__tile" />
            <span className="shell-mark__text">PeraSwarm</span>
        </div>
    );
}

export default LoginPage;
