import { ArrowRight, Shield } from "lucide-react";
import { FaDiscord } from "react-icons/fa6";
import Link from "next/link";

const LOGIN_MEDIA_IMAGES = [
  "https://csrptickets-storage.s3.us-east-1.amazonaws.com/CSRP_Staff_Team.webp",
  "https://csrptickets-storage.s3.us-east-1.amazonaws.com/CSRP_Staff_Team.webp",
  "https://csrptickets-storage.s3.us-east-1.amazonaws.com/CSRP_Staff_Team.webp"
];

export default function Home() {
  return (
    <main className="login-page">
      <section className="login-media">
        <div className="login-media-slides" aria-hidden="true">
          {LOGIN_MEDIA_IMAGES.map((src, index) => (
            <div className="login-media-slide" style={{ backgroundImage: `url("${src}")` }} key={`${src}-${index}`} />
          ))}
        </div>
        <div className="login-overlay" />
        <div className="quote">
          <Shield size={28} />
          <h2>Thanks to the help of CSRP Utilities, we've been able to add features specific to our server that no other bot could offer, like an advanced infractions system, fast staff management commands like /reinstate, and the addition of our smart hits system which automatically reviews hits and sends them for a secondary staff review.</h2>
          <span>- PointlessTalderson (Director)</span>
        </div>
      </section>
      <section className="login-panel">
        <div className="crumbs">
          <Link href="/">Home</Link>
          <span>/</span>
          <strong>Login</strong>
        </div>
        <div className="login-card">
          <div className="login-brand">
            <img src="https://csrptickets-storage.s3.us-east-1.amazonaws.com/018b50d0d885271446f02f157fe8e00a.png" alt="CSRP Utilities Logo" width="112" />
            <span>CSRP Utilities</span>
          </div>
          <p className="auth-eyebrow">CALIFORNIA STATE ROLEPLAY</p>
          <h1>Log in to CSRP Utilities</h1>
          <p>Sign in using your Discord account to continue.</p>
          <a className="button primary wide" href="/api/login">
            <FaDiscord size={18} />
            Continue with Discord
            <ArrowRight size={18} />
          </a>
        </div>
      </section>
    </main>
  );
}
