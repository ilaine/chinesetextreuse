'''
This script takes the compiled results compiles and aligns quotes
between documents that the scholar is interested in. If no documents
are listed, this operates on the entire corpus, but can be very slow
depending on corpus size.
'''

import pickle, os, time, sys
import numpy as np
import json
import re

import Levenshtein
from multiprocessing import Pool
from itertools import repeat, chain

#********************#
# DOCUMENTS TO ALIGN #
#********************#

# Align quotes occuring between the following documents. Provide at
# least two. If None, all quotes will be aligned. If your corpus contains
# signficant reuse, this may be slow.
alignment_docs = None
#["003 卷耳-前漢-毛", "003 卷耳-唐-孔穎達", "006 桃夭-唐-孔穎達", "007 兔罝-唐-孔穎達", "009 漢廣-唐-孔穎達", "011 麟之趾-前漢-毛", "011 麟之趾-唐-孔穎達", "011 麟之趾-後漢-鄭玄", "017 行露-唐-孔穎達", "017 行露-後漢-鄭玄", "020 摽有梅-唐-孔穎達", "024 何彼襛矣-前漢-毛", "024 何彼襛矣-唐-孔穎達", "025 騶虞-前漢-毛", "025 騶虞-唐-孔穎達", "031 擊鼓-前漢-毛", "031 擊鼓-唐-孔穎達", "031 擊鼓-後漢-鄭玄", "032 凱風-前漢-毛", "032 凱風-唐-孔穎達", "037 旄丘-前漢-毛", "037 旄丘-唐-孔穎達", "037 旄丘-後漢-鄭玄", "047 君子偕老-前漢-毛", "047 君子偕老-唐-孔穎達", "048 桑中-前漢-毛", "048 桑中-唐-孔穎達", "048 桑中-後漢-鄭玄", "050 定之方中-前漢-毛", "050 定之方中-唐-孔穎達", "050 定之方中-後漢-鄭玄", "065 黍離-唐-孔穎達", "065 黍離-後漢-鄭玄"]


#**********************#
# ALIGNMENT PARAMETERS #
#**********************#

# Match, mismatch, and gap scores
MATCHSCORE = 1
MISALIGNSCORE = -1
MISMATCHSCORE = -1

# Limit the length of text that will be aligned
# This significantly speeds up the algorithm when
# aligning very long quotes. This divides the quotes
# into blocks of CHUNKLIM length. It tries to divide
# the chunks in places where the alignment is exact
# So OVERLAP looks at the 10 character before and after
# the proposed break. When it finds RANGEMATCH exact
# characters, it inserts a break in the middle.
CHUNKLIM = 200
OVERLAP = 10
RANGEMATCH = 6


#************************#
# Input and output files #
#************************#
# Input
CORPUSRESULTS = "corpus_results.txt"
# Output
OUTPUTFILE = "corpus_alignment.txt"



#****************#
# GLOBAL TRACKER #
#****************#
# to track alignment progress
tracker = 0

#**********************#
# FUNCTION DEFINITIONS #
#**********************#

# Divide texts into smaller chunks of a certain maximum length
# To optimze for later alignment, divide texts in areas of high
# homology
def divtexts(quote1, quote2, chunklimit,overlap,rangecheck):
    chunks = len(quote1)//chunklimit
    qs1 = 0
    qs2 = 0
    chunkedTexts = []
    for chunk in range(chunks + 1):
        if chunk != chunks:
            tqe1 = (chunk+1)*chunklimit
            tqe2 = (chunk+1)*chunklimit

            # retreive the boundary region
            tqr1 = quote1[tqe1-rangecheck:tqe1+rangecheck]
            tqr2 = quote2[tqe2-rangecheck:tqe2+rangecheck]

            # identify a stretch of identical overlap and save the midpoint
            qe1 = None
            qe2 = None
            for i in range(len(tqr1)-overlap):
                for j in range(len(tqr2)-overlap):
                    if tqr1[i:i+overlap] == tqr2[j:j+overlap]:
                        qe1 = tqe1 - rangecheck + i + overlap//2
                        qe2 = tqe2 - rangecheck + i + overlap//2
            # If no region is identified, just cut at initial boundary
            if not qe1:
                qe1 = tqe1
                qe2 = tqe2

            # save the cut region
            chunkedTexts.append([quote1[qs1:qe1],quote2[qs2:qe2]])

            # move the start of the next chunk to the end of the last one
            qs1 = qe1
            qs2 = qe2
        else:
            if len(quote1[qs1:]) == 0 or len(quote2[qs2:]) == 0:
                chunkedTexts[-1][0] += quote1[qs1:]
                chunkedTexts[-1][1] += quote2[qs2:]
            else:
                chunkedTexts.append([quote1[qs1:],quote2[qs2:]])
    return chunkedTexts

# Algorithm used for quote alignment. Insights into how this work come from the original
# Needleman-Wunsch article, but also from http://www.biorecipes.com/DynProgBasic/code.html
def align(quote1, quote2,matchscore=MATCHSCORE,misalignscore=MISALIGNSCORE,mismatchscore=MISMATCHSCORE, chunklim=CHUNKLIM):

    # The alignment algorithm is O(n^2) so only alinging short chunks speeds
    # the process up. Here I divide each sequence into smaller chunks for
    # alignment and then recombine them at the end.
    if len(quote1) > chunklim:
        textchunks = divtexts(quote1, quote2, CHUNKLIM, OVERLAP, RANGEMATCH)
    else:
        textchunks = [[quote1, quote2]]

    # Empty strings to store the calculated quotes
    total_quote_1 = ""
    total_quote_2 = ""

    # Iterate through each of the divided texts
    for texts in textchunks:

        # Create alignment matrix
        matrix = np.zeros([len(texts[0])+1,len(texts[1])+1])
        # prep matrix:
        for i in range(len(texts[0])+1):
            matrix[i][0] = -i
        for j in range(len(texts[1])+1):
            matrix[0][j] = -j


        # Iterate through both texts and fill out the matrix
        for i in range(len(texts[0])):
            for j in range(len(texts[1])):
                # Get characters to compare
                c1 = texts[0][i]
                c2 = texts[1][j]

                # If they are the same, give them the matching score.
                # Otherwise, give them the mismatch score
                if c1 == c2:
                    score = matchscore
                else:
                    score = mismatchscore

                # get the pertinent matrix location (which will be both plus one)
                matrixrow = i+1
                matrixcolumn = j+1

                # Calculate scores from top, left, and diagnol
                upperscore = matrix[i][j+1] + misalignscore
                leftscore = matrix[i+1][j] + misalignscore
                diagonal = matrix[i][j] + score

                # Select the highest score and place it in the box
                currentscore = max([upperscore, leftscore, diagonal])
                matrix[matrixrow][matrixcolumn] = currentscore

        # Create two empty strings for the traceback
        stringa = ""
        stringb = ""

        # Traceback to get the best alignment
        # Begin at the bottom right corner
        i = len(matrix)-1
        j = len(matrix[0])-1

        # Get the final score
        finalscore = matrix[i][j]

        # While i or j is above zero, trace backwards
        while i > 0 or j > 0:
            # Get the maximum value from the adjacent squares
            upper = matrix[i][j - 1]
            left  = matrix[i-1][j]
            diagonal = matrix[i-1][j-1]
            maxval = max([upper, left, diagonal])

            # If the maximum value is the diagonal, move diagonally
            if maxval == diagonal:
                i -= 1
                j -= 1
                stringa = texts[0][i] + stringa
                try:
                    stringb = texts[1][j] + stringb
                except:
                    print(texts, i, j)
            # If the maximum value is above, insert gap into stringa
            elif maxval == upper:
                j -= 1
                stringa = " "+stringa
                stringb = texts[1][j] + stringb
            # If the maximum value is left, insert gap into stringb
            elif maxval == left:
                i -= 1
                stringa = texts[0][i] + stringa
                stringb = " "+stringb

        # add all parts of the string together
        total_quote_1 += stringa
        total_quote_2 += stringb

    # Trim the bits left over from searching algorithm. In certain edge cases
    # the ends are not the same
    # IW: Commented, uncomment the following lines to trim
    # while total_quote_1[-1] == " " or total_quote_2[-1] == " ":
    #     total_quote_1 = total_quote_1[:-1]
    #     total_quote_2 = total_quote_2[:-1]
    # while total_quote_1[-1] != total_quote_2[-1]:
    #     total_quote_1 = total_quote_1[:-1]
    #     total_quote_2 = total_quote_2[:-1]

    return total_quote_1, total_quote_2

# IW: Retrieve text from the original corpus
def original(data,orig):
    data[6] = get_original(data, orig, 0, 4, 6)
    data[7] = get_original(data, orig, 1, 5, 7)
    return data

# IW: Get the original segment with the newly added spaces
def get_original(data, metadata, a, b, c):
    start = int(data[b])
    end = int(data[b]) + len(data[c])
    res = metadata[data[a]][start:end]

    if ' ' in data[c]:
        spaces = [m.start() for m in re.finditer(' ', data[c])]
        for pos in spaces:
            res = insert_space(res,pos)
    return res[:len(data[c])]

# IW: Insert spaces to match aligned text
def insert_space(text, pos):
    return text[:pos]+' '+text[pos:]

# Run the process
def runalignment(content,totallength,orig=False):
    global tracker
    info = content.split("\t")
    # If the quotes are identical, no need to align them
    if float(info[3]) != 1.0:
        # Run the alignment algorithm
        aligneda, alignedb = align(info[6], info[7])

        # Save the information
        info[6] = aligneda
        info[7] = alignedb

        # IW: Retrieve text from original corpus
        # useful if variants were replaced in prepare_corpus
        if orig is not False:
            info = original(info,orig)

        content = "\t".join(info)
    tracker += 1
    if tracker % 1000 == 0:
        sys.stdout.write(f"{tracker} out of {totallength} aligned          \r")
        sys.stdout.flush()
    return content

#*********************#
# START OF MAIN LOGIC #
#*********************#

if __name__=='__main__':
    # Start a global timer
    gs = time.time()

    # Initialize thread pool for parallel processing
    pool = Pool()
    runtimes = []
    save_contents = []

    # Results container
    results = []
    # Iterate through each line in the file aligning the results using map
    with open(CORPUSRESULTS, "r") as rf:
        contents = rf.read().split("\n")
        contents = contents[1:]

        # If alignment_docs have been provided, extract the relevant quotes
        if alignment_docs:
            use_contents = []
            pairs = set()
            for t1 in alignment_docs:
                for t2 in alignment_docs:
                    if t1 != t2:
                        pairs.add((t1, t2))

            for line in contents:
                info = line.split("\t")
                pair = (info[0], info[1])
                if pair in pairs:
                    use_contents.append(line)
            contents = use_contents

    # IW: Open json where the original text has been stored
    # only if prepare_corpus.py was used with -v option
    try:
        with open('./corpus.json','r') as of:
            orig = json.load(of)
            results = pool.starmap(runalignment,zip(contents,repeat(len(contents)),repeat(orig)))
    except FileNotFoundError:
        print('There is no variants in your corpus or you chose not to take them into account')
        results = pool.starmap(runalignment,zip(contents,repeat(len(contents))))


    # Remove blank results and flatten the list
    save_contents = [s for s in results if len(s) > 0]

    with open(OUTPUTFILE, "w") as wf:
        wf.write("\n".join(save_contents))

    ge = time.time()
    gt = ge-gs
    print(f"Global Operation completed in {gt:.2f} seconds")
