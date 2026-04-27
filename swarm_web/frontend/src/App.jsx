import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import "./App.css";

import LoginPage from "./pages/login.jsx";
import ProjectPage from "./pages/projectPage.jsx";

const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

/* 🔐 AUTH CHECK HOOK */
function useAuth() {
    const [loading, setLoading] = useState(true);
    const [isAuth, setIsAuth] = useState(false);

    // 1. Pulled this out so we can call it manually after login/logout
    async function checkAuth() {
        setLoading(true);
        try {
            const res = await fetch(`${apiBase}/auth/me`, {
                method: "GET",
                credentials: "include",
            });
            
            const data = await res.json();
            
            // 2. We now check for the user object instead of res.ok
            setIsAuth(!!data.user); 
        } catch {
            setIsAuth(false);
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        checkAuth();
    }, []);

    // 3. Return checkAuth so the app can trigger it
    return { loading, isAuth, checkAuth }; 
}

function App() {
    const { loading, isAuth, checkAuth } = useAuth();

    if (loading) {
        return (
            <div className="loading-screen">
                <div className="loading-card">
                    <div className="eyebrow">PeraSwarm Console</div>
                    <div className="auth-heading">Loading secure workspace</div>
                    <p className="auth-copy">Preparing the control surface and validating session access.</p>
                </div>
            </div>
        );
    }

    return (
        <Routes>
            <Route path="/" element={<HomeRedirect isAuth={isAuth} />} />
            {/* 4. Pass checkAuth to the routes that change auth state */}
            <Route path="/login" element={<LoginRoute isAuth={isAuth} revalidateAuth={checkAuth} />} />
            <Route path="/projects" element={<ProjectsRoute isAuth={isAuth} revalidateAuth={checkAuth} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
    );
}

/* 🚀 HOME ROUTE */
function HomeRedirect({ isAuth }) {
    return <Navigate to={isAuth ? "/projects" : "/login"} replace />;
}

/* 🔑 LOGIN ROUTE */
function LoginRoute({ isAuth, revalidateAuth }) {
    const navigate = useNavigate();

    if (isAuth) {
        return <Navigate to="/projects" replace />;
    }

    async function handleLoginSuccess() {
        // 5. Update the global auth state BEFORE navigating
        await revalidateAuth(); 
        navigate("/projects", { replace: true });
    }

    return <LoginPage onLoginSuccess={handleLoginSuccess} />;
}

/* 📁 PROJECT ROUTE */
function ProjectsRoute({ isAuth, revalidateAuth }) {
    const navigate = useNavigate();

    if (!isAuth) {
        return <Navigate to="/login" replace />;
    }

    async function handleLogout() {
        try {
            await fetch(`${apiBase}/auth/logout`, {
                method: "POST",
                credentials: "include",
            });
        } finally {
            // 6. Clear global auth state and push to login
            await revalidateAuth();
            navigate("/login", { replace: true });
        }
    }

    return <ProjectPage onLogout={handleLogout} />;
}

export default App;