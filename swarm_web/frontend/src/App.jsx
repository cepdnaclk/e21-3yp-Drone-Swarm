import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import "./App.css";

import LoginPage from "./pages/login.jsx";
import ProjectPage from "./pages/projectPage.jsx";
import AdminLayout from "./pages/admin/adminLayout.jsx";
import AdminDashboard from "./pages/admin/dashboard.jsx";
import AdminUsersPage from "./pages/admin/usersPage.jsx";
import AdminProjectsPage from "./pages/admin/projectsAdminPage.jsx";

const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

/* 🔐 AUTH CHECK HOOK */
function useAuth() {
    const [loading, setLoading] = useState(true);
    const [user, setUser] = useState(null);

    async function checkAuth() {
        setLoading(true);
        try {
            const res = await fetch(`${apiBase}/auth/me`, {
                method: "GET",
                credentials: "include",
            });

            const data = await res.json();
            setUser(data.user || null);
        } catch {
            setUser(null);
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        checkAuth();
    }, []);

    return {
        loading,
        user,
        isAuth: !!user,
        isAdmin: !!user?.isAdmin,
        checkAuth,
    };
}

function App() {
    const { loading, isAuth, isAdmin, user, checkAuth } = useAuth();

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
            <Route path="/login" element={<LoginRoute isAuth={isAuth} revalidateAuth={checkAuth} />} />
            <Route
                path="/projects"
                element={
                    <ProjectsRoute
                        isAuth={isAuth}
                        isAdmin={isAdmin}
                        revalidateAuth={checkAuth}
                    />
                }
            />
            <Route
                path="/admin"
                element={
                    <AdminRoute isAuth={isAuth} isAdmin={isAdmin} user={user} revalidateAuth={checkAuth} />
                }
            >
                <Route index element={<AdminDashboard />} />
                <Route path="users" element={<AdminUsersPage />} />
                <Route path="projects" element={<AdminProjectsPage />} />
            </Route>
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
        await revalidateAuth();
        navigate("/projects", { replace: true });
    }

    return <LoginPage onLoginSuccess={handleLoginSuccess} />;
}

/* 📁 PROJECT ROUTE */
function ProjectsRoute({ isAuth, isAdmin, revalidateAuth }) {
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
            await revalidateAuth();
            navigate("/login", { replace: true });
        }
    }

    return <ProjectPage onLogout={handleLogout} isAdmin={isAdmin} />;
}

/* 🛡️ ADMIN ROUTE */
function AdminRoute({ isAuth, isAdmin, user, revalidateAuth }) {
    const navigate = useNavigate();

    if (!isAuth) return <Navigate to="/login" replace />;
    if (!isAdmin) return <Navigate to="/projects" replace />;

    async function handleLogout() {
        try {
            await fetch(`${apiBase}/auth/logout`, {
                method: "POST",
                credentials: "include",
            });
        } finally {
            await revalidateAuth();
            navigate("/login", { replace: true });
        }
    }

    return <AdminLayout user={user} onLogout={handleLogout} />;
}

export default App;
