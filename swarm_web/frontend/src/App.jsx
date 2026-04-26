import { Navigate, Route, Routes, useNavigate, useEffect, useState } from "react-router-dom";
import LoginPage from "./pages/login.jsx";
import ProjectPage from "./pages/projectPage.jsx";

const apiBase = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

/* 🔐 AUTH CHECK HOOK (cookie-based) */
function useAuth() {
    const [loading, setLoading] = useState(true);
    const [isAuth, setIsAuth] = useState(false);

    useEffect(() => {
        async function checkAuth() {
            try {
                const res = await fetch(`${apiBase}/auth/me`, {
                    method: "GET",
                    credentials: "include", // 🔥 cookie sent automatically
                });

                setIsAuth(res.ok);
            } catch {
                setIsAuth(false);
            } finally {
                setLoading(false);
            }
        }

        checkAuth();
    }, []);

    return { loading, isAuth };
}

function App() {
    const { loading, isAuth } = useAuth();

    if (loading) {
        return <div>Loading...</div>;
    }

    return (
        <Routes>
            <Route path="/" element={<HomeRedirect isAuth={isAuth} />} />
            <Route path="/login" element={<LoginRoute isAuth={isAuth} />} />
            <Route path="/projects" element={<ProjectsRoute isAuth={isAuth} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
    );
}

/* 🚀 HOME ROUTE */
function HomeRedirect({ isAuth }) {
    return <Navigate to={isAuth ? "/projects" : "/login"} replace />;
}

/* 🔑 LOGIN ROUTE */
function LoginRoute({ isAuth }) {
    const navigate = useNavigate();

    if (isAuth) {
        return <Navigate to="/projects" replace />;
    }

    function handleLoginSuccess() {
        navigate("/projects", { replace: true });
    }

    return <LoginPage onLoginSuccess={handleLoginSuccess} />;
}

/* 📁 PROJECT ROUTE */
function ProjectsRoute({ isAuth }) {
    const navigate = useNavigate();

    if (!isAuth) {
        return <Navigate to="/login" replace />;
    }

    function handleLogout() {
        // optional backend logout endpoint
        fetch(`${apiBase}/auth/logout`, {
            method: "POST",
            credentials: "include",
        }).finally(() => {
            navigate("/login", { replace: true });
        });
    }

    return <ProjectPage onLogout={handleLogout} />;
}

export default App;