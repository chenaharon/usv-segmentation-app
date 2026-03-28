import numpy as np
from openpyxl import Workbook
from legacy.Segmentation import (
    Preprocessing as preprocessing,
    Syllables_Detection2 as syllablesDetection,
    Rearrange_signal as rearrangeSignal,
    Check_length_Call as checkLengthCall,
)
from utils import SEGMENTATION_RESULT_COLUMNS, get_output_filename


##################################################
### consts
##################################################
FRAME_LENGTH = 0.006
OVERLAP = 0.7
THRESH = 20
HARMONY_TH = 0.009


def create_segmentation_workbook():
    """Create and initialize Excel workbook for segmentation results."""
    book = Workbook()
    sheet = book.active
    # Full column list: Path + metadata columns + segmentation-specific columns + Duration
    title = ['Path'] + SEGMENTATION_RESULT_COLUMNS + ['Duration (time)']
    sheet.append(title)
    return (book, sheet)


def trim_leading_silence(signal):
    """
    Remove leading silence (zeros) from audio signal.
    
    This function detects and removes silent segments at the beginning of the signal.
    If the signal starts with zeros, it finds the first non-zero segment and shifts
    the signal to start from that point, effectively trimming the leading silence.
    
    The function uses a two-step detection:
    1. First checks if the signal starts with zeros
    2. If so, finds where the continuous zero sequence ends by detecting changes
       in the difference of differences of zero indices
    
    Args:
        signal: numpy array of audio signal values
        
    Returns:
        tuple: (trimmed_signal, ind2) where:
            - trimmed_signal: signal with leading silence removed (or original if no leading silence)
            - ind2: index array used for further processing, [[0],[0]] if no trimming occurred
    """
    # if there is a 'silent' start (zeros), skipping to the "real" start:
    ind = np.where(signal == 0)
    is_empty = ind[0].size == 0
    if not(is_empty) and ind[0][0] == 0:
      DiffInd = np.diff(np.diff(ind))
      ind2 = np.where(DiffInd != 0)
      is_empty = ind2[0].size == 0
      if not(is_empty):
        for i in range(0,len(signal)-int(ind2[0])):
          signal[i] = signal[i+int(ind2[0])]
        i = range(len(signal)-int(ind2[0]),len(signal))
        signal = np.delete(signal,i)
      else:
        ind2 = [[0],[0]]
    else:
      ind2 = [[0],[0]]
    return (signal, ind2)


def segment_single_recording(signal, Fs, frame_length, overlap, thresh, harmony_th, signal_file_name):
    """
    Perform segmentation on a single audio recording.
    
    This function processes a single recording through the complete segmentation pipeline:
    1. Preprocesses the signal (removes mean, applies filters)
    2. Trims leading silence (zeros) from the signal
    3. Detects syllables in the signal
    4. If syllables are found, rearranges and validates the detected segments
    
    The function returns the validated start/end time matrix for detected syllables,
    or an empty list if no syllables were found.
    
    Args:
        signal: numpy array of raw audio signal values
        Fs: sampling rate (frequency) of the signal
        frame_length: frame length parameter for syllable detection
        overlap: overlap parameter for syllable detection
        thresh: threshold parameter for syllable detection
        harmony_th: harmony threshold parameter for syllable detection
        signal_file_name: name/path of the signal file (used for logging/debugging)
        
    Returns:
        list: StEndMatF - list of [start_time, end_time] pairs for detected syllables.
              Returns empty list [] if no syllables were detected.
    """
    signal = preprocessing(signal, Fs)
    signal, ind2 = trim_leading_silence(signal)
    
    _,_,_,_,ClassLPC,SyllabelVec,SignalPath = syllablesDetection(signal,Fs,frame_length,overlap, thresh, harmony_th, signal_file_name, ind2)
    
    if any(SyllabelVec):
      StartEndNew = rearrangeSignal(signal,Fs,ClassLPC.time1) #StartEndNew - times vector
      StEndMatF = checkLengthCall(StartEndNew)
      # logger.debug(StEndMatF)
      return StEndMatF
    else:
      return []


def append_calls_to_sheet(sheet, signal_path, mother_value, matgen_value, name_value, sex_value, pupgen_value, age_value, session_value, rec_num_value, calls):
    """
    Append detected syllable calls to Excel sheet.
    
    For each call in the calls list, calculates the duration and appends a row
    to the sheet with all metadata and timing information.
    
    Args:
        sheet: openpyxl worksheet object to append rows to
        signal_path: path/name of the signal file
        mother_value: mother identifier value
        matgen_value: mother genotype value
        name_value: name identifier value
        sex_value: sex value
        pupgen_value: offspring genotype value
        age_value: age value
        session_value: session value
        rec_num_value: recording number value
        calls: list of [start_time, end_time] pairs (like StEndMatF)
    """
    for i in range(len(calls)):
      Duration = calls[i][1] - calls[i][0]
      new_row = [signal_path, mother_value, matgen_value, name_value, sex_value, pupgen_value, age_value, session_value, rec_num_value, calls[i][0], calls[i][1], Duration]
      sheet.append(new_row)


def run_segmentation(file_name, SignalVec, signal_name, rate, mother, matgen, name, sex, pupgen, age, session, rec_num, missing_count, logger):
    """
    Run segmentation pipeline on recordings.
    
    Processes all recordings in SignalVec, detects syllables, and writes results
    to an Excel workbook. The workbook is saved to outputs/{file_name}.
    
    Uses segmentation constants defined in this module: FRAME_LENGTH, OVERLAP, THRESH, HARMONY_TH.
    
    Args:
        file_name: name of the metadata file (used for output filename)
        SignalVec: list of audio signal arrays
        signal_name: list of signal file names/paths
        rate: sampling rate
        mother: list of mother identifiers
        matgen: list of mother genotype values
        name: list of name identifiers
        sex: list of sex values
        pupgen: list of offspring genotype values
        age: list of age values
        session: list of session values
        rec_num: list of recording number values
        missing_count: number of missing recordings
        logger: logger instance for logging
        
    Returns:
        str: path to the saved Excel file (output_xlsx)
    """
    logger.info(f"Segmentation started (recordings={len(SignalVec)}, missing={missing_count})")
    
    Fs = rate
    siz = len(SignalVec)
    book, sheet = create_segmentation_workbook()
    
    # Process each recording: detect syllables and extract start/end times
    total_calls = 0
    for recording_idx in range(siz):
      signal = SignalVec[recording_idx]
      # Segment the recording: preprocess, detect syllables, validate segments
      # Returns list of [start_time, end_time] pairs, or empty list if no syllables found
      calls = segment_single_recording(signal, Fs, FRAME_LENGTH, OVERLAP, THRESH, HARMONY_TH, signal_name[recording_idx])
      
      # Write detected syllables to Excel workbook
      if calls:
        total_calls += len(calls)
        append_calls_to_sheet(
          sheet,
          signal_name[recording_idx],
          mother[recording_idx],
          matgen[recording_idx],
          name[recording_idx],
          sex[recording_idx],
          pupgen[recording_idx],
          age[recording_idx],
          session[recording_idx],
          rec_num[recording_idx],
          calls
        )
      
      # Log progress every 50 recordings or at the end
      if (recording_idx + 1) % 50 == 0 or (recording_idx + 1) == siz:
        progress_pct = ((recording_idx + 1) / siz) * 100
        logger.info(f"Segmentation progress: {recording_idx + 1}/{siz} recordings ({progress_pct:.1f}%) | Total syllables detected: {total_calls}")
    
    # Export segmentation results to Excel
    output_filename = get_output_filename(file_name)
    output_xlsx = f'outputs/{output_filename}'
    book.save(output_xlsx)
    logger.info(f"Segmentation finished (calls={siz}, exported to {output_xlsx})")
    
    return output_xlsx

