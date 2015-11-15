"""
Tools for working with still images and videos based on the ffmpeg library.
"""
import os
import subprocess as sp

def make_movie(stills_directory, input_file_format='*.png',
               movie_filename='', frames_per_second=30):
    """ 
    Make a movie out of a sequence of still frames.

    Parameters
    ----------
    frames_per_second : int
        The number of stills that get packed into one second of video.
    input_file_format : str
        The format of the still images that are read in.
    movie_filename : str
        The filename to apply to the video file.
        Default is empty string, in which case a filename is autogenerated..
    stills_directory : str
        The relative path to the directory that contains the still images. 
    """
    # Generate a movie filename if one was not provided.
    if not movie_filename:
        movie_filename = ''.join((stills_directory, '.mp4'))

    # Prepare the arguments for the call to ffmpeg.
    input_file_pattern = ''.join(
            ['\'', os.path.join(stills_directory, input_file_format), '\''])
    codec = 'libx264'
    command = ' '.join(['ffmpeg -framerate', str(frames_per_second), 
                        '-pattern_type glob -i', input_file_pattern, 
                        '-c:v', codec, movie_filename])
    print command
    # shell=True is considered a bit of a security risk, but without it
    # this cammand won't parse properly 
    sp.call(command, shell=True)

def break_movie(movie_filename, stills_directory, output_file_format='.jpg'):
    """ 
    Create a set of numbered still images from a movie.
    Run from the directory containing the movie file.
    
    Parameters
    ----------
    movie_directory : str
        The relative path to the directory that contains the video file. 
    movie_filename : str
        The name of the video file.
    output_file_format : str
        The format of the output still images, indicated by the suffix.
    stills_directory
        The relative path to the directory that contains the still images. 
    """
    # Prepare the arguments for the call to ffmpeg
    output_files = ''.join(['%05d', output_file_format])
    output_file_pattern = os.path.join(stills_directory, output_files)

    command = ' '.join(['ffmpeg -i', movie_filename,  output_file_pattern])
    print command
    # shell=True is considered a bit of a security risk, but without it
    # this cammand won't parse properly 
    sp.call(command, shell=True)
