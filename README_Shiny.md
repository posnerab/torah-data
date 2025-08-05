# Torah Data Explorer - R Shiny App

This R Shiny application provides an interactive interface to explore and visualize data from the `Data.xlsx` file.

## Features

- **Multi-sheet Support**: Browse and select from different sheets within the Excel file
- **Interactive Data Tables**: View data in sortable, filterable DataTables
- **Dynamic Charting**: Create various chart types (bar, line, scatter, histogram, box plots)
- **Boolean Filtering**: Filter data using checkboxes for true/false columns
- **Professional UI**: Clean dashboard interface using Shiny Dashboard

## Prerequisites

- R (version 3.5 or higher)
- RStudio (recommended for easier package management)

## Installation

1. **Install Required Packages**: Run the following in R console:
   ```r
   source("requirements.R")
   ```

2. **Alternative Manual Installation**: Install packages individually:
   ```r
   install.packages(c("shiny", "shinydashboard", "DT", "readxl", "dplyr", "ggplot2", "plotly", "tidyr"))
   ```

## Running the App

1. **From R Console**:
   ```r
   source("app.R")
   ```

2. **From RStudio**:
   - Open `app.R` in RStudio
   - Click "Run App" button or press Ctrl+Shift+Enter

3. **From Command Line**:
   ```bash
   R -e "shiny::runApp()"
   ```

## Usage Guide

### Data Overview Tab
- View information about the Excel file and available sheets
- Select a sheet to load into the application
- See current sheet statistics (rows, columns, column names)

### Data Tables Tab
- View the loaded data in an interactive table
- Sort by clicking column headers
- Filter using the search boxes at the top of each column
- Navigate through pages of data

### Charts Tab
- **Chart Type**: Select from Bar Chart, Line Chart, Scatter Plot, Histogram, or Box Plot
- **Variables**: Choose X-axis, Y-axis, color, and facet variables
- **Boolean Filters**: Use checkboxes to filter true/false columns
- **Update Chart**: Click to generate the visualization

## File Structure

```
torah-data/
├── app.R                 # Main Shiny application
├── requirements.R        # Package installation script
├── README_Shiny.md      # This file
└── Data.xlsx            # Your data file
```

## Troubleshooting

### Common Issues

1. **Package Installation Errors**:
   - Ensure you have the latest version of R
   - Try installing packages from CRAN: `install.packages("package_name", repos="https://cran.rstudio.com/")`

2. **File Not Found**:
   - Ensure `Data.xlsx` is in the same directory as `app.R`
   - Check file permissions

3. **Memory Issues**:
   - For large Excel files, consider loading only specific sheets
   - Close other R sessions to free memory

### Performance Tips

- For large datasets, the app may take a moment to load
- Use the filtering options to work with smaller subsets of data
- Consider breaking very large Excel files into smaller sheets

## Customization

The app can be easily customized by modifying `app.R`:

- **Add new chart types**: Extend the switch statement in the chart output section
- **Modify UI layout**: Adjust the dashboard layout in the UI section
- **Add new features**: Extend the server logic with additional reactive elements

## Support

If you encounter issues:
1. Check that all required packages are installed
2. Verify the `Data.xlsx` file is accessible
3. Check R console for error messages
4. Ensure you have sufficient memory for your dataset size 