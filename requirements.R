# Required R packages for the Torah Data Explorer Shiny App
# Install these packages before running the app

# Set CRAN mirror
options(repos = c(CRAN = "https://cran.rstudio.com/"))

# Function to install packages if not already installed
install_if_missing <- function(packages) {
  for (package in packages) {
    if (!require(package, character.only = TRUE, quietly = TRUE)) {
      install.packages(package, dependencies = TRUE)
    }
  }
}

# Core Shiny packages
install_if_missing(c("shiny", "shinydashboard"))

# Data manipulation and visualization
install_if_missing(c("DT", "readxl", "dplyr", "ggplot2", "plotly", "tidyr"))

# Optional but recommended packages for better performance
install_if_missing(c("data.table", "scales"))

# Load all packages
library(shiny)
library(shinydashboard)
library(DT)
library(readxl)
library(dplyr)
library(ggplot2)
library(plotly)
library(tidyr)

cat("All packages installed and loaded successfully!\n")