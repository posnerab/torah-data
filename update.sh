#!/bin/bash
# Shell script to update the Torah Data Explorer app
# Usage: ./update.sh

echo "🔄 Updating Torah Data Explorer app..."

# Check if R is available
if ! command -v Rscript &> /dev/null; then
    echo "❌ Error: Rscript not found. Please install R first."
    exit 1
fi

# Check if required files exist
if [ ! -f "app.R" ]; then
    echo "❌ Error: app.R not found in current directory"
    exit 1
fi

if [ ! -f "Data.xlsx" ]; then
    echo "❌ Error: Data.xlsx not found in current directory"
    exit 1
fi

# Run the quick update script
echo "📤 Deploying to Shinyapps.io..."
Rscript quick_update.R

if [ $? -eq 0 ]; then
    echo "✅ App updated successfully!"
    echo "🌐 Your app is available at: https://YOUR_ACCOUNT_NAME.shinyapps.io/torah-data-explorer/"
else
    echo "❌ Update failed. Check the error messages above."
    exit 1
fi 