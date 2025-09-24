import './globals.css';

export const metadata = {
  title: 'RPA_JOBBOX',
  description: 'Login page with Firebase auth',
}

export default function RootLayout({ children, }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  )
}
