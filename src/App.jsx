// src/App.jsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { SignedIn, SignedOut } from "@clerk/clerk-react";

import MainLayout from './layouts/MainLayout';
import HomeFeed from './pages/HomeFeed';
import TopicsDashboard from './pages/TopicsDashboard';
import ProfileSettings from './pages/ProfileSettings';
import Login from './pages/Login';
import { WebSocketProvider } from './context/WebSocketContext';

export default function App() {
  return (
    <BrowserRouter>
      {/* Unauthenticated View: Show the Login Page */}
      <SignedOut>
        <Login />
      </SignedOut>

      {/* Authenticated View: Show the Dashboard and connect to WebSockets */}
      <SignedIn>
        <WebSocketProvider>
          <Routes>
            <Route path="/" element={<MainLayout />}>
              <Route index element={<HomeFeed />} />
              <Route path="topics" element={<TopicsDashboard />} />
              <Route path="profile" element={<ProfileSettings />} />
            </Route>
          </Routes>
        </WebSocketProvider>
      </SignedIn>
    </BrowserRouter>
  );
}