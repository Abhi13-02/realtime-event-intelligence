// src/App.jsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { SignedIn, SignedOut } from "@clerk/clerk-react";

import MainLayout from "./layouts/MainLayout";
import HomeFeed from "./pages/HomeFeed";
import TopicsDashboard from "./pages/TopicsDashboard";
import ProfileSettings from "./pages/ProfileSettings";
import Login from "./pages/Login";
import { WebSocketProvider } from "./context/WebSocketContext";
import TopicDeepDive from "./pages/TopicDeepDive";
import ApiProvider from "./context/ApiProvider";

export default function App() {
  return (
    <BrowserRouter>
      {/* View for logged-out users */}
      <SignedOut>
        <Login />
      </SignedOut>

      {/* View for logged-in users */}
      <SignedIn>
        {/* Wrap the ApiProvider around everything else */}
        <ApiProvider>
          <WebSocketProvider>
            <Routes>
              <Route path="/" element={<MainLayout />}>
                <Route index element={<HomeFeed />} />
                <Route path="topics" element={<TopicsDashboard />} />
                <Route path="topics/:topicId" element={<TopicDeepDive />} />
                {/* You can also add your TopicDeepDive route here later */}
                <Route path="profile" element={<ProfileSettings />} />
              </Route>
            </Routes>
          </WebSocketProvider>
        </ApiProvider>
      </SignedIn>
    </BrowserRouter>
  );
}
