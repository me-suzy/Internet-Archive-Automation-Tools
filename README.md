# 🏛️ Internet Archive Automation Tools

Advanced automation tools for Internet Archive (archive.org) with comprehensive upload management, error detection, and file organization.

## 🚀 Features

### 📂 **Recursive Folder Processing**
- **Deep scanning** of all subfolders without level limits
- **Smart categorization** based on PDF presence
- **Alphabetical sorting** with special character handling
- **Progress tracking** across multiple sessions

### 📤 **Intelligent Upload Management**
- **Bulk PDF uploads** to Internet Archive with all associated files
- **Auto-form completion** (Description, Subjects, Date, Collection)
- **Chrome automation** with remote debugging support
- **Daily upload limits** (configurable, default: 200)

### 🔍 **Advanced Error Detection**
- **404/505/503 error monitoring** after uploads
- **5-minute delayed verification** for accurate results
- **Detailed error logging** with XML content extraction
- **Failed upload tracking** with timestamped reports

### 📁 **Smart File Organization**
- **Priority-based file selection** (.mobi, .epub, .djvu, .docx, .doc, .lit, .rtf)
- **Automatic file moving** for non-PDF folders
- **Duplicate handling** with overwrite capabilities
- **Extension-based filtering** (excludes .jpg, .png)

### 💾 **Persistent State Management**
- **JSON-based progress tracking** (`state_archive.json`)
- **Session continuity** across days
- **Unit-level processing** memory
- **Daily reset** with progress preservation

## 📋 Requirements

### Software Dependencies
```bash
pip install selenium
```

### Chrome Setup
1. **Run Chrome with remote debugging:**
   ```batch
   start_chrome_debug.bat
   ```

2. **Chrome will start with debugging port 9222**

### Directory Structure
```
📁 Source: g:\ARHIVA\B\
📁 Destination: d:\3\
📄 State file: state_archive.json
```

## 🔧 Configuration

### Main Settings
```python
ARCHIVE_PATH = Path(r"g:\ARHIVA\B")
MOVE_PATH = Path(r"d:\3")
MAX_UPLOADS_PER_DAY = 200
```

### Priority Extensions (for non-PDF folders)
```python
PRIORITY_EXTENSIONS = ['.mobi', '.epub', '.djvu', '.docx', '.doc', '.lit', '.rtf']
```

### Ignored Extensions
```python
IGNORE_EXTENSIONS = ['.jpg', '.png']
```

## 🚀 Usage

### 1. Prepare Chrome
```batch
# Run this first to start Chrome with debugging
start_chrome_debug.bat
```

### 2. Run the Uploader
```bash
python "FINAL - Internet Archive upload 2025 (cu verificare eroare 505).py"
```

### 3. Monitor Progress
- **Real-time console output** with detailed progress
- **JSON state file** updated continuously
- **Error reports** saved as timestamped .txt files

## 📊 Processing Logic

### For Folders WITH PDFs:
1. **Upload ALL files** (except .jpg/.png) to Internet Archive
2. **Auto-complete** archive.org form fields:
   - Title: Sanitized folder name
   - Description: Same as title
   - Subjects: Same as title
   - Date: 1983-12-13 (configurable)
   - Collection: Community texts (texts:opensource)
3. **Track upload** in state file
4. **Wait 10 seconds** between uploads

### For Folders WITHOUT PDFs:
1. **Find priority file** (first match from priority extensions)
2. **Copy to d:\3\** with overwrite
3. **Mark as processed**

## 🔍 Error Detection System

### After Upload Monitoring
- **5-minute wait** after last upload
- **Scan all Chrome tabs** for error indicators
- **Extract error details** from pop-ups
- **Generate timestamped reports**

### Supported Error Codes
- **404**: Not Found
- **505**: HTTP Version Not Supported
- **503**: Service Unavailable
- **Network errors**: Connection problems

### Error Report Format
```
📖 filename.pdf (Cod: 404, Status: Not Found)
📄 Titlu: Document Title
🚨 Eroare: 404 Not Found
🕒 Timp: 2025-08-04T12:30:45
📝 Detalii: XML error content...
```

## 📈 Progress Tracking

### State File Structure (`state_archive.json`)
```json
{
  "date": "2025-08-04",
  "processed_folders": ["folder1", "folder2"],
  "processed_units": ["unit1", "unit2"],
  "uploads_today": 45,
  "folders_moved": 12,
  "total_files_uploaded": 123,
  "last_processed_folder": "Current Folder"
}
```

### Daily Reset Behavior
- **New day**: Reset counters, preserve partial progress
- **Same day**: Continue from last position
- **Partial uploads**: Resume incomplete folders

## ⚙️ Advanced Features

### Form Auto-Completion
- **Smart title sanitization** (removes special characters)
- **iframe handling** for rich text editors
- **JavaScript execution** for disabled fields
- **Multiple verification rounds** (10 attempts)
- **Comprehensive field validation**

### Chrome Integration
- **Remote debugging** connection (port 9222)
- **Multiple tab management**
- **Window handle tracking**
- **Automatic cleanup** and recovery

### File Name Processing
- **Fakepath removal** (`C:\fakepath\`)
- **Extension stripping** for titles
- **Dash to space conversion**
- **Word capitalization**
- **Sequence number removal**

## 🛠️ Troubleshooting

### Common Issues

**Chrome Connection Failed:**
```bash
# Make sure Chrome is running with debugging
start_chrome_debug.bat
```

**Upload Errors:**
- Check Chrome tabs for error pop-ups
- Verify Internet Archive login
- Ensure stable internet connection

**File Path Issues:**
- Use absolute paths in configuration
- Check folder permissions
- Verify source directories exist

### Debug Mode
Enable detailed logging by running with verbose output:
```python
# Add this at the top of the script for debug mode
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 📝 File Structure

```
Internet-Archive-Automation-Tools/
├── FINAL - Internet Archive upload 2025 (cu verificare eroare 505).py
├── start_chrome_debug.bat
├── state_archive.json (generated)
├── upload_errors_with_404_505_*.txt (generated)
└── README.md
```

## 🏆 Key Benefits

- **🔄 Automated workflow** from folder scan to upload completion
- **📊 Comprehensive monitoring** with detailed progress tracking
- **🛡️ Error resilience** with automatic retry and recovery
- **📈 Scalable processing** handles thousands of files efficiently
- **💡 Smart organization** with priority-based file selection
- **🔍 Quality assurance** through post-upload error verification

## ⚡ Performance

- **Concurrent processing** with 10-second upload intervals
- **Efficient scanning** with recursive folder traversal
- **Memory optimization** through unit-based processing
- **State persistence** prevents duplicate work
- **Chrome reuse** minimizes overhead

---

**📞 Need Help?** Check the console output for detailed progress information and error messages.

**🔄 Updates:** This tool is actively maintained and improved based on real-world usage patterns.
