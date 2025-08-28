#!/usr/bin/env Rscript
# Update Script for Torah Data Explorer
# Use this script to redeploy your app after making changes

# Load required packages
library(rsconnect)

# Configuration
APP_NAME <- "torah-data-explorer"
APP_TITLE <- "Torah Data Explorer"
APP_FILES <- c("app.R", "Data.xlsx")

# Function to check if files exist
check_files <- function() {
  missing_files <- c()
  for (file in APP_FILES) {
    if (!file.exists(file)) {
      missing_files <- c(missing_files, file)
    }
  }
  
  if (length(missing_files) > 0) {
    cat("❌ Missing files:", paste(missing_files, collapse = ", "), "\n")
    cat("Please ensure all files are in the current directory.\n")
    return(FALSE)
  }
  
  cat("✅ All required files found.\n")
  return(TRUE)
}

# Function to show file sizes
show_file_info <- function() {
  cat("\n📁 File Information:\n")
  for (file in APP_FILES) {
    size_mb <- round(file.size(file) / (1024 * 1024), 2)
    cat(sprintf("  %s: %.2f MB\n", file, size_mb))
  }
}

# Main update function
update_app <- function() {
  cat("🔄 Torah Data Explorer - App Update\n")
  cat("=====================================\n\n")
  
  # Check if rsconnect is configured
  tryCatch({
    rsconnect::accounts()
    cat("✅ Shinyapps.io account configured.\n")
  }, error = function(e) {
    cat("❌ Shinyapps.io account not configured.\n")
    cat("Please run: rsconnect::setAccountInfo(name='YOUR_ACCOUNT', token='YOUR_TOKEN', secret='YOUR_SECRET')\n")
    return(FALSE)
  })
  
  # Check files
  if (!check_files()) {
    return(FALSE)
  }
  
  # Show file information
  show_file_info()
  
  # Confirm update
  cat("\n🚀 Ready to update your deployed app?\n")
  cat("This will replace the current version on Shinyapps.io.\n")
  cat("Press Enter to continue or Ctrl+C to cancel...\n")
  
  # Wait for user input (optional - remove if you want automatic deployment)
  readline()
  
  # Deploy the app
  cat("\n📤 Deploying updated app...\n")
  cat("This may take several minutes for large files.\n")
  
  tryCatch({
    start_time <- Sys.time()
    
    rsconnect::deployApp(
      appName = APP_NAME,
      appTitle = APP_TITLE,
      appFiles = APP_FILES,
      forceUpdate = TRUE,
      logLevel = "normal"
    )
    
    end_time <- Sys.time()
    deployment_time <- round(as.numeric(difftime(end_time, start_time, units = "mins")), 1)
    
    cat("\n✅ App updated successfully!\n")
    cat(sprintf("⏱️  Deployment time: %.1f minutes\n", deployment_time))
    cat("\n🌐 Your app is available at:\n")
    cat("   https://YOUR_ACCOUNT_NAME.shinyapps.io/torah-data-explorer/\n")
    
  }, error = function(e) {
    cat("\n❌ Deployment failed:\n")
    cat("   Error:", e$message, "\n")
    cat("\n💡 Troubleshooting tips:\n")
    cat("   - Check your internet connection\n")
    cat("   - Verify your Shinyapps.io credentials\n")
    cat("   - Ensure you have sufficient account limits\n")
    cat("   - Try again in a few minutes\n")
  })
}

# Run the update
update_app() 