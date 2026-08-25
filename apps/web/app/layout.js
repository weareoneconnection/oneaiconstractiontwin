import "./globals.css";
import "cesium/Build/Cesium/Widgets/widgets.css";
import ServiceWorker from "../components/ServiceWorker";

export const metadata = {
  title: "OneAI Construction Twin Enterprise Pilot",
  description: "AI-Native Digital Twin for Construction & Infrastructure",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg" },
};

export const viewport = {
  themeColor: "#06101c",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="app">{children}</div>
        <ServiceWorker />
      </body>
    </html>
  );
}
