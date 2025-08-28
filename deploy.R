# Deployment script for Shinyapps.io
# This script will help deploy your Torah Data Explorer app

# Install and load rsconnect package for deployment
if (!require(rsconnect)) {
  install.packages("rsconnect")
}
library(rsconnect)

# Load all required packages
library(shiny)
library(shinydashboard)
library(DT)
library(readxl)
library(dplyr)
library(ggplot2)
library(plotly)
library(tidyr)

# Function to check if all required packages are available
check_packages <- function() {
  required_packages <- c("shiny", "shinydashboard", "DT", "readxl", "dplyr", 
                        "ggplot2", "plotly", "tidyr")
  
  missing_packages <- c()
  for (pkg in required_packages) {
    if (!require(pkg, character.only = TRUE, quietly = TRUE)) {
      missing_packages <- c(missing_packages, pkg)
    }
  }
  
  if (length(missing_packages) > 0) {
    cat("Missing packages:", paste(missing_packages, collapse = ", "), "\n")
    cat("Please run requirements.R first to install all packages.\n")
    return(FALSE)
  } else {
    cat("All required packages are available.\n")
    return(TRUE)
  }
}

# Check if Data.xlsx exists
check_data_file <- function() {
  if (!file.exists("Data.xlsx")) {
    cat("Error: Data.xlsx file not found in current directory.\n")
    return(FALSE)
  } else {
    cat("Data.xlsx file found.\n")
    return(TRUE)
  }
}

# Main deployment function
deploy_app <- function() {
  cat("=== Torah Data Explorer - Shinyapps.io Deployment ===\n\n")
  
  # Check prerequisites
  if (!check_packages()) {
    return(FALSE)
  }
  
  if (!check_data_file()) {
    return(FALSE)
  }
  
  cat("\nReady to deploy! Follow these steps:\n")
  cat("1. Make sure you have a Shinyapps.io account\n")
  cat("2. Run the following command to configure your account:\n")
  cat("   rsconnect::setAccountInfo(name='<ACCOUNT>', token='<TOKEN>', secret='<SECRET>')\n")
  cat("3. Then run: rsconnect::deployApp()\n\n")
  
  cat("Would you like to proceed with deployment? (y/n): ")
  response <- readline()
  
  if (tolower(response) == "y") {
    cat("\nDeploying app to Shinyapps.io...\n")
    tryCatch({
      rsconnect::deployApp(
        appName = "torah-data-explorer",
        appTitle = "Torah Data Explorer",
        appFiles = c("app.R", "Data.xlsx"),
        forceUpdate = TRUE
      )
      cat("\n✅ Deployment successful!\n")
      cat("Your app should be available at: https://your-username.shinyapps.io/torah-data-explorer/\n")
    }, error = function(e) {
      cat("\n❌ Deployment failed:", e$message, "\n")
      cat("Please check your Shinyapps.io configuration.\n")
    })
  } else {
    cat("\nDeployment cancelled.\n")
  }
}

# Run deployment check
deploy_app() 