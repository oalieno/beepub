import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.beepub.app",
  appName: "BeePub",
  webDir: "build",
  ios: {
    // Hide the form navigation bar (up/down arrows + checkmark) above the keyboard
    scrollEnabled: false,
  },
  plugins: {
    Keyboard: {
      // Hide the accessory bar (prev/next/done) above the keyboard
      hideAccessoryBar: true,
    },
  },
};

export default config;
