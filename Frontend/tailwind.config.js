/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}"
  ],
  theme: {
    extend: {
      fontFamily: {
        'sans': ['Urbanist', 'ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'Noto Sans', 'sans-serif'],
      },
      colors: {
        // Design System Colors
        primary: {
          DEFAULT: '#6B21A8', // Primary purple
          50: '#F3E8FF',
          100: '#E9D5FF',
          200: '#D8B4FE',
          300: '#C084FC',
          400: '#A855F7',
          500: '#6B21A8',
          600: '#580F9A',
          700: '#4C1275',
          800: '#3B0F5C',
          900: '#2D0A47',
        },
        secondary: {
          DEFAULT: '#00FFD1', // Teal/cyan
          50: '#F0FDFA',
          100: '#CCFBF1',
          200: '#99F6E4',
          300: '#5EEAD4',
          400: '#2DD4BF',
          500: '#00FFD1',
          600: '#00C2B3',
          700: '#0F766E',
          800: '#115E59',
          900: '#134E4A',
        },
        accent: {
          DEFAULT: '#E0FFFF', // Light blue
          50: '#F0FFFF',
          100: '#E0FFFF',
          200: '#B0E0E6',
          300: '#87CEEB',
          400: '#87CEFA',
          500: '#E0FFFF',
          600: '#B0E0E6',
          700: '#87CEEB',
          800: '#5F9EA0',
          900: '#4682B4',
        },
        neutral: {
          DEFAULT: '#1F2937', // Dark gray
          50: '#F9FAFB',
          100: '#F3F4F6',
          200: '#E5E7EB',
          300: '#D1D5DB',
          400: '#9CA3AF',
          500: '#6B7280',
          600: '#4B5563',
          700: '#374151',
          800: '#1F2937',
          900: '#111827',
        },
        // Background colors
        background: {
          app: '#F9FAFB',
          card: '#FFFFFF',
          highlight: 'rgba(0, 255, 209, 0.05)', // Secondary with 5% opacity
          alert: 'rgba(224, 255, 255, 0.05)', // Accent with 5% opacity
        },
        // Button colors
        button: {
          primary: {
            DEFAULT: '#6B21A8',
            hover: '#580F9A',
            active: '#4C1275',
            disabled: '#A78BFA',
            text: '#FFFFFF',
            textDisabled: '#E0D7F8',
          },
          secondary: {
            DEFAULT: '#00FFD1',
            hover: '#33FFE8',
            active: '#00C2B3',
            disabled: '#A0F7F2',
            text: '#1F2937',
            textDisabled: '#4B5563',
          },
          destructive: {
            DEFAULT: '#E0FFFF',
            hover: '#B0E0E6',
            active: '#87CEEB',
            disabled: '#F0FFFF',
            text: '#1F2937',
            textDisabled: '#4B5563',
          },
        },
        // Table colors
        table: {
          header: '#6B21A8',
          row: '#1F2937',
          hover: 'rgba(107, 33, 168, 0.05)',
          selected: 'rgba(107, 33, 168, 0.15)',
          border: '#E5E7EB',
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
}

