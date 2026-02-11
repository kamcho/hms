#!/bin/bash

# Tailwind CSS Minification Script
# This script extracts Tailwind classes from the template and generates minified CSS

echo "🎨 Tailwind CSS Minifier for Inventory Add Item Page"
echo "======================================================"

# Check if Node.js and npm are installed
if ! command -v npm &> /dev/null; then
    echo "❌ npm not found. Installing Node.js and npm..."
    echo "Run: sudo apt update && sudo apt install nodejs npm -y"
    exit 1
fi

# Navigate to project directory
cd "$(dirname "$0")"

# Install Tailwind CSS if not already installed
if [ ! -d "node_modules/tailwindcss" ]; then
    echo "📦 Installing Tailwind CSS..."
    npm init -y
    npm install -D tailwindcss
fi

# Create Tailwind config if it doesn't exist
if [ ! -f "tailwind.config.js" ]; then
    echo "⚙️  Creating Tailwind configuration..."
    cat > tailwind.config.js << 'EOF'
module.exports = {
  content: [
    './inventory/templates/**/*.html',
    './home/templates/**/*.html',
    './users/templates/**/*.html',
    './accounts/templates/**/*.html',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
EOF
fi

# Create input CSS file
echo "📝 Creating input CSS..."
cat > input.css << 'EOF'
@tailwind base;
@tailwind components;
@tailwind utilities;
EOF

# Build minified CSS
echo "🔨 Building minified Tailwind CSS..."
npx tailwindcss -i ./input.css -o ./static/css/tailwind.min.css --minify

echo "✅ Tailwind CSS has been minified!"
echo "📁 Output: static/css/tailwind.min.css"
echo ""
echo "📊 File sizes:"
ls -lh static/css/tailwind.min.css 2>/dev/null || echo "Output file not found"
echo ""
echo "🔗 To use in your template, add:"
echo '<link rel="stylesheet" href="{% static "css/tailwind.min.css" %}">'
