#!/bin/bash

# Tailwind CSS Minification Script
# This script extracts Tailwind classes from the templates and generates minified CSS

echo "🎨 Tailwind CSS Minifier"
echo "======================================================"

# Navigate to project directory
cd "$(dirname "$0")"

# Build minified CSS using the local binary
echo "🔨 Building minified Tailwind CSS..."
./tailwindcss-linux-x64 -i ./users/static/users/css/tailwind_input.css -o ./users/static/users/css/tailwind.css --minify

echo "✅ Tailwind CSS has been minified!"
echo "📁 Output: users/static/users/css/tailwind.css"
echo ""
echo "📊 File sizes:"
ls -lh users/static/users/css/tailwind.css 2>/dev/null || echo "Output file not found"
echo ""
echo "🔗 Used in your template as:"
echo '<link rel="stylesheet" href="{% static '\''users/css/tailwind.css'\'' %}">'
