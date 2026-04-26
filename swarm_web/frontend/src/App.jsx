import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import LoginPage from "./pages/login.jsx";
import ProjectPage from "./pages/projectPage.jsx";

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomeRedirect />} />
      <Route path="/login" element={<LoginRoute />} />
      <Route path="/projects" element={<ProjectsRoute />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function HomeRedirect() {
  const token = localStorage.getItem("authToken");
  return <Navigate to={token ? "/projects" : "/login"} replace />;
}

function LoginRoute() {
  const navigate = useNavigate();
  const token = localStorage.getItem("authToken");

  if (token) {
    return <Navigate to="/projects" replace />;
  }

  function handleLoginSuccess(nextToken) {
    if (nextToken) {
      localStorage.setItem("authToken", nextToken);
      navigate("/projects", { replace: true });
    }
  }

  return <LoginPage onLoginSuccess={handleLoginSuccess} />;
}

function ProjectsRoute() {
  const navigate = useNavigate();
  const token = localStorage.getItem("authToken");

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  function handleLogout() {
    localStorage.removeItem("authToken");
    navigate("/login", { replace: true });
  }

  return <ProjectPage onLogout={handleLogout} />;
}

export default App;
