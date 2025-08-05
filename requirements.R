# Required R packages for the Torah Data Explorer Shiny App
# Install these packages before running the app

# Core Shiny packages
install.packages("shiny")
install.packages("shinydashboard")

# Data manipulation and visualization
install.packages("DT")
install.packages("readxl")
install.packages("dplyr")
install.packages("ggplot2")
install.packages("plotly")
install.packages("tidyr")

# Optional but recommended packages for better performance
install.packages("data.table")
install.packages("scales")

# Load all packages
library(shiny)
library(shinydashboard)
library(DT)
library(readxl)
library(dplyr)
library(ggplot2)
library(plotly)
library(tidyr) 